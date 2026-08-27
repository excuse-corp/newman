#ifdef _WIN32

#define WIN32_LEAN_AND_MEAN
#ifndef LUA_TOKEN
#define LUA_TOKEN 0x4
#endif
#ifndef WRITE_RESTRICTED
#define WRITE_RESTRICTED 0x8
#endif

#include <aclapi.h>
#include <bcrypt.h>
#include <sddl.h>
#include <windows.h>

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {
constexpr DWORD kRunnerFailureExit = 127;

struct RunnerFailure : std::runtime_error {
  explicit RunnerFailure(const std::string& detail) : std::runtime_error(detail) {}
};

void fail(const std::string& detail) {
  std::cerr << "newman-windows-acl-run: " << detail << "\n";
  throw RunnerFailure(detail);
}

std::string utf8(const std::wstring& value) {
  if (value.empty()) return {};
  const int size = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
  if (size <= 0) return "<utf8 conversion failed>";
  std::string result(size, '\0');
  WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), size, nullptr, nullptr);
  return result;
}

std::wstring win32_message(DWORD code) {
  wchar_t* buffer = nullptr;
  const DWORD chars = FormatMessageW(
      FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
      nullptr,
      code,
      MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
      reinterpret_cast<LPWSTR>(&buffer),
      0,
      nullptr);
  std::wstring message = chars == 0 || buffer == nullptr ? L"unknown error" : std::wstring(buffer, chars);
  if (buffer != nullptr) LocalFree(buffer);
  while (!message.empty() && (message.back() == L'\r' || message.back() == L'\n' || message.back() == L'.' || message.back() == L' ')) {
    message.pop_back();
  }
  return message;
}

[[noreturn]] void fail_last_error(const std::string& api, const std::wstring& context = L"") {
  const DWORD code = GetLastError();
  std::string detail = api + " failed (Win32 " + std::to_string(code) + ": " + utf8(win32_message(code)) + ")";
  if (!context.empty()) detail += ": " + utf8(context);
  fail(detail);
}

struct LocalFreeDeleter {
  void operator()(void* ptr) const noexcept {
    if (ptr != nullptr) LocalFree(ptr);
  }
};
using LocalPtr = std::unique_ptr<void, LocalFreeDeleter>;

struct Handle {
  HANDLE value = nullptr;
  Handle() = default;
  explicit Handle(HANDLE handle) : value(handle) {}
  ~Handle() { reset(); }
  Handle(const Handle&) = delete;
  Handle& operator=(const Handle&) = delete;
  Handle(Handle&& other) noexcept : value(other.value) { other.value = nullptr; }
  Handle& operator=(Handle&& other) noexcept {
    if (this != &other) {
      reset();
      value = other.value;
      other.value = nullptr;
    }
    return *this;
  }
  HANDLE get() const { return value; }
  HANDLE* put() {
    reset();
    return &value;
  }
  HANDLE release() {
    HANDLE out = value;
    value = nullptr;
    return out;
  }
  explicit operator bool() const { return value != nullptr && value != INVALID_HANDLE_VALUE; }
  void reset(HANDLE next = nullptr) {
    if (value != nullptr && value != INVALID_HANDLE_VALUE) CloseHandle(value);
    value = next;
  }
};

struct ParsedArgs {
  std::wstring workspace;
  std::wstring temp;
  std::wstring mode;
  std::wstring write_sid;
  std::wstring temp_write_sid;
  std::vector<std::wstring> command;
};

ParsedArgs parse_args(int argc, wchar_t** argv) {
  ParsedArgs parsed;
  int index = 2;
  for (; index < argc; ++index) {
    std::wstring token = argv[index];
    if (token == L"--") {
      ++index;
      break;
    }
    if (index + 1 >= argc) fail("missing value after " + utf8(token));
    std::wstring value = argv[++index];
    if (token == L"--workspace") parsed.workspace = value;
    else if (token == L"--temp") parsed.temp = value;
    else if (token == L"--mode") parsed.mode = value;
    else if (token == L"--write-sid") parsed.write_sid = value;
    else if (token == L"--temp-write-sid") parsed.temp_write_sid = value;
    else fail("unknown argument: " + utf8(token));
  }
  if (parsed.workspace.empty()) fail("missing --workspace");
  if (parsed.temp.empty()) fail("missing --temp");
  if (parsed.mode != L"read-only" && parsed.mode != L"workspace-write") fail("unknown mode: " + utf8(parsed.mode));
  for (; index < argc; ++index) parsed.command.emplace_back(argv[index]);
  if (parsed.command.empty()) fail("missing command after --");
  if (parsed.mode == L"read-only" && (!parsed.write_sid.empty() || !parsed.temp_write_sid.empty())) {
    fail("read-only does not accept --write-sid or --temp-write-sid");
  }
  if (parsed.mode == L"workspace-write" && (parsed.write_sid.empty() || parsed.temp_write_sid.empty())) {
    fail("workspace-write requires --write-sid and --temp-write-sid");
  }
  return parsed;
}

std::wstring full_path(const std::wstring& path) {
  DWORD needed = GetFullPathNameW(path.c_str(), 0, nullptr, nullptr);
  if (needed == 0) fail_last_error("GetFullPathNameW", path);
  std::wstring result(needed, L'\0');
  DWORD written = GetFullPathNameW(path.c_str(), needed, result.data(), nullptr);
  if (written == 0 || written >= needed) fail_last_error("GetFullPathNameW", path);
  result.resize(written);
  return result;
}

std::wstring lower_path(std::wstring value) {
  std::transform(value.begin(), value.end(), value.begin(), [](wchar_t ch) { return static_cast<wchar_t>(towlower(ch)); });
  while (!value.empty() && (value.back() == L'\\' || value.back() == L'/')) value.pop_back();
  return value;
}

bool path_within(const std::wstring& path, const std::wstring& root) {
  std::wstring p = lower_path(full_path(path));
  std::wstring r = lower_path(full_path(root));
  if (p == r) return true;
  if (r.empty()) return false;
  return p.size() > r.size() && p.compare(0, r.size(), r) == 0 && (p[r.size()] == L'\\' || p[r.size()] == L'/');
}

void require_directory(const std::wstring& label, const std::wstring& path) {
  DWORD attrs = GetFileAttributesW(path.c_str());
  if (attrs == INVALID_FILE_ATTRIBUTES) fail_last_error("GetFileAttributesW", label + L"=" + path);
  if ((attrs & FILE_ATTRIBUTE_DIRECTORY) == 0) fail(utf8(label) + " is not a directory: " + utf8(path));
  if ((attrs & FILE_ATTRIBUTE_REPARSE_POINT) != 0) fail(utf8(label) + " must not be a reparse point: " + utf8(path));
}

std::string wide_to_utf8_bytes(const std::wstring& value) {
  return utf8(value);
}

std::vector<std::uint8_t> sha256(const std::string& data) {
  BCRYPT_ALG_HANDLE algorithm = nullptr;
  BCRYPT_HASH_HANDLE hash = nullptr;
  if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) != 0) fail("BCryptOpenAlgorithmProvider failed");
  DWORD object_length = 0;
  DWORD returned = 0;
  if (BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH, reinterpret_cast<PUCHAR>(&object_length), sizeof(object_length), &returned, 0) != 0) {
    BCryptCloseAlgorithmProvider(algorithm, 0);
    fail("BCryptGetProperty(BCRYPT_OBJECT_LENGTH) failed");
  }
  std::vector<std::uint8_t> object(object_length);
  std::vector<std::uint8_t> digest(32);
  if (BCryptCreateHash(algorithm, &hash, object.data(), object_length, nullptr, 0, 0) != 0) {
    BCryptCloseAlgorithmProvider(algorithm, 0);
    fail("BCryptCreateHash failed");
  }
  if (BCryptHashData(hash, reinterpret_cast<PUCHAR>(const_cast<char*>(data.data())), static_cast<ULONG>(data.size()), 0) != 0 ||
      BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) != 0) {
    BCryptDestroyHash(hash);
    BCryptCloseAlgorithmProvider(algorithm, 0);
    fail("BCrypt SHA256 failed");
  }
  BCryptDestroyHash(hash);
  BCryptCloseAlgorithmProvider(algorithm, 0);
  return digest;
}

std::uint32_t subauth(const std::vector<std::uint8_t>& digest, size_t offset) {
  std::uint32_t value = static_cast<std::uint32_t>(digest[offset]) |
                        (static_cast<std::uint32_t>(digest[offset + 1]) << 8) |
                        (static_cast<std::uint32_t>(digest[offset + 2]) << 16) |
                        (static_cast<std::uint32_t>(digest[offset + 3]) << 24);
  return value % ((1u << 30) - 1u) + 1u;
}

std::wstring workspace_write_sid(const std::wstring& workspace) {
  auto digest = sha256(wide_to_utf8_bytes(full_path(workspace)));
  return L"S-1-4-" + std::to_wstring(subauth(digest, 0)) + L"-" + std::to_wstring(subauth(digest, 4));
}

std::wstring temp_write_sid(const std::wstring& temp) {
  std::string data = std::string("temp", 4) + '\0' + wide_to_utf8_bytes(full_path(temp));
  auto digest = sha256(data);
  return L"S-1-4-" + std::to_wstring(subauth(digest, 0)) + L"-" + std::to_wstring(subauth(digest, 4)) + L"-1";
}

LocalPtr sid_from_string(const std::wstring& sid_text) {
  PSID sid = nullptr;
  if (!ConvertStringSidToSidW(sid_text.c_str(), &sid)) fail_last_error("ConvertStringSidToSidW", sid_text);
  return LocalPtr(sid);
}

LocalPtr everyone_sid() {
  DWORD size = SECURITY_MAX_SID_SIZE;
  PSID sid = LocalAlloc(LMEM_FIXED, size);
  if (sid == nullptr) fail_last_error("LocalAlloc(Everyone SID)");
  if (!CreateWellKnownSid(WinWorldSid, nullptr, sid, &size)) {
    LocalFree(sid);
    fail_last_error("CreateWellKnownSid(WinWorldSid)");
  }
  return LocalPtr(sid);
}

LocalPtr logon_sid(HANDLE token) {
  DWORD size = 0;
  GetTokenInformation(token, TokenGroups, nullptr, 0, &size);
  if (GetLastError() != ERROR_INSUFFICIENT_BUFFER) fail_last_error("GetTokenInformation(TokenGroups size)");
  std::vector<std::uint8_t> buffer(size);
  if (!GetTokenInformation(token, TokenGroups, buffer.data(), size, &size)) fail_last_error("GetTokenInformation(TokenGroups)");
  auto* groups = reinterpret_cast<TOKEN_GROUPS*>(buffer.data());
  for (DWORD i = 0; i < groups->GroupCount; ++i) {
    if ((groups->Groups[i].Attributes & SE_GROUP_LOGON_ID) != 0) {
      DWORD sid_size = GetLengthSid(groups->Groups[i].Sid);
      PSID copy = LocalAlloc(LMEM_FIXED, sid_size);
      if (copy == nullptr) fail_last_error("LocalAlloc(Logon SID)");
      if (!CopySid(sid_size, copy, groups->Groups[i].Sid)) {
        LocalFree(copy);
        fail_last_error("CopySid(Logon SID)");
      }
      return LocalPtr(copy);
    }
  }
  fail("current token has no logon SID");
}

void grant_write(const std::wstring& path, PSID sid) {
  EXPLICIT_ACCESSW access{};
  access.grfAccessPermissions = FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE | DELETE;
  access.grfAccessMode = GRANT_ACCESS;
  access.grfInheritance = SUB_CONTAINERS_AND_OBJECTS_INHERIT;
  access.Trustee.TrusteeForm = TRUSTEE_IS_SID;
  access.Trustee.TrusteeType = TRUSTEE_IS_GROUP;
  access.Trustee.ptstrName = static_cast<LPWSTR>(sid);

  PACL old_dacl = nullptr;
  PSECURITY_DESCRIPTOR descriptor = nullptr;
  DWORD status = GetNamedSecurityInfoW(const_cast<LPWSTR>(path.c_str()), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, nullptr, nullptr, &old_dacl, nullptr, &descriptor);
  if (status != ERROR_SUCCESS) {
    SetLastError(status);
    fail_last_error("GetNamedSecurityInfoW", path);
  }
  LocalPtr descriptor_holder(descriptor);

  PACL new_dacl = nullptr;
  status = SetEntriesInAclW(1, &access, old_dacl, &new_dacl);
  if (status != ERROR_SUCCESS) {
    SetLastError(status);
    fail_last_error("SetEntriesInAclW", path);
  }
  LocalPtr dacl_holder(new_dacl);

  status = SetNamedSecurityInfoW(const_cast<LPWSTR>(path.c_str()), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, nullptr, nullptr, new_dacl, nullptr);
  if (status != ERROR_SUCCESS) {
    SetLastError(status);
    fail_last_error("SetNamedSecurityInfoW", path);
  }
}

void revoke_write_best_effort(const std::wstring& path, PSID sid) {
  EXPLICIT_ACCESSW access{};
  access.grfAccessPermissions = 0;
  access.grfAccessMode = REVOKE_ACCESS;
  access.grfInheritance = SUB_CONTAINERS_AND_OBJECTS_INHERIT;
  access.Trustee.TrusteeForm = TRUSTEE_IS_SID;
  access.Trustee.TrusteeType = TRUSTEE_IS_GROUP;
  access.Trustee.ptstrName = static_cast<LPWSTR>(sid);

  PACL old_dacl = nullptr;
  PSECURITY_DESCRIPTOR descriptor = nullptr;
  DWORD status = GetNamedSecurityInfoW(const_cast<LPWSTR>(path.c_str()), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, nullptr, nullptr, &old_dacl, nullptr, &descriptor);
  if (status != ERROR_SUCCESS) return;
  LocalPtr descriptor_holder(descriptor);

  PACL new_dacl = nullptr;
  status = SetEntriesInAclW(1, &access, old_dacl, &new_dacl);
  if (status != ERROR_SUCCESS) return;
  LocalPtr dacl_holder(new_dacl);
  SetNamedSecurityInfoW(const_cast<LPWSTR>(path.c_str()), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION, nullptr, nullptr, new_dacl, nullptr);
}

Handle create_restricted_token(HANDLE base_token, const std::vector<PSID>& restricting_sids) {
  std::vector<SID_AND_ATTRIBUTES> sids;
  sids.reserve(restricting_sids.size());
  for (PSID sid : restricting_sids) sids.push_back(SID_AND_ATTRIBUTES{sid, 0});
  Handle restricted;
  if (!CreateRestrictedToken(
          base_token,
          DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED,
          0,
          nullptr,
          0,
          nullptr,
          static_cast<DWORD>(sids.size()),
          sids.data(),
          restricted.put())) {
    fail_last_error("CreateRestrictedToken");
  }
  return restricted;
}

std::wstring quote_arg(const std::wstring& arg) {
  if (arg.empty()) return L"\"\"";
  bool needs_quotes = arg.find_first_of(L" \t\n\v\"") != std::wstring::npos;
  if (!needs_quotes) return arg;
  std::wstring result = L"\"";
  size_t slash_count = 0;
  for (wchar_t ch : arg) {
    if (ch == L'\\') {
      ++slash_count;
    } else if (ch == L'"') {
      result.append(slash_count * 2 + 1, L'\\');
      result.push_back(ch);
      slash_count = 0;
    } else {
      result.append(slash_count, L'\\');
      slash_count = 0;
      result.push_back(ch);
    }
  }
  result.append(slash_count * 2, L'\\');
  result.push_back(L'"');
  return result;
}

std::wstring command_line(const std::vector<std::wstring>& argv) {
  std::wstring result;
  for (const auto& arg : argv) {
    if (!result.empty()) result.push_back(L' ');
    result += quote_arg(arg);
  }
  return result;
}

Handle create_kill_on_close_job() {
  Handle job(CreateJobObjectW(nullptr, nullptr));
  if (!job) fail_last_error("CreateJobObjectW");
  JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
  limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
  if (!SetInformationJobObject(job.get(), JobObjectExtendedLimitInformation, &limits, sizeof(limits))) {
    fail_last_error("SetInformationJobObject(JobObjectExtendedLimitInformation)");
  }
  return job;
}

DWORD run_child(HANDLE token, const std::vector<std::wstring>& argv) {
  std::wstring cmdline = command_line(argv);
  STARTUPINFOW startup{};
  startup.cb = sizeof(startup);
  startup.dwFlags = STARTF_USESTDHANDLES;
  startup.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
  startup.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
  startup.hStdError = GetStdHandle(STD_ERROR_HANDLE);
  if (startup.hStdInput != INVALID_HANDLE_VALUE && startup.hStdInput != nullptr) SetHandleInformation(startup.hStdInput, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
  if (startup.hStdOutput != INVALID_HANDLE_VALUE && startup.hStdOutput != nullptr) SetHandleInformation(startup.hStdOutput, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
  if (startup.hStdError != INVALID_HANDLE_VALUE && startup.hStdError != nullptr) SetHandleInformation(startup.hStdError, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);

  PROCESS_INFORMATION process_info{};
  std::vector<wchar_t> mutable_cmdline(cmdline.begin(), cmdline.end());
  mutable_cmdline.push_back(L'\0');
  if (!CreateProcessAsUserW(
          token,
          nullptr,
          mutable_cmdline.data(),
          nullptr,
          nullptr,
          TRUE,
          CREATE_SUSPENDED,
          nullptr,
          nullptr,
          &startup,
          &process_info)) {
    fail_last_error("CreateProcessAsUserW", cmdline);
  }
  Handle process(process_info.hProcess);
  Handle thread(process_info.hThread);
  Handle job = create_kill_on_close_job();
  if (!AssignProcessToJobObject(job.get(), process.get())) fail_last_error("AssignProcessToJobObject");
  if (ResumeThread(thread.get()) == static_cast<DWORD>(-1)) fail_last_error("ResumeThread");
  WaitForSingleObject(process.get(), INFINITE);
  DWORD exit_code = 1;
  if (!GetExitCodeProcess(process.get(), &exit_code)) fail_last_error("GetExitCodeProcess");
  return exit_code;
}

DWORD run(int argc, wchar_t** argv) {
  ParsedArgs parsed = parse_args(argc, argv);
  parsed.workspace = full_path(parsed.workspace);
  parsed.temp = full_path(parsed.temp);
  require_directory(L"--workspace", parsed.workspace);
  require_directory(L"--temp", parsed.temp);
  if (parsed.mode == L"workspace-write" && (path_within(parsed.temp, parsed.workspace) || path_within(parsed.workspace, parsed.temp))) {
    fail("--temp must be outside --workspace");
  }
  if (parsed.mode == L"workspace-write") {
    if (parsed.write_sid != workspace_write_sid(parsed.workspace)) fail("--write-sid does not match --workspace");
    if (parsed.temp_write_sid != temp_write_sid(parsed.temp)) fail("--temp-write-sid does not match --temp");
  }

  Handle base_token;
  if (!OpenProcessToken(
          GetCurrentProcess(),
          TOKEN_DUPLICATE | TOKEN_ASSIGN_PRIMARY | TOKEN_QUERY | TOKEN_ADJUST_DEFAULT | TOKEN_ADJUST_SESSIONID,
          base_token.put())) {
    fail_last_error("OpenProcessToken");
  }

  LocalPtr keepalive_everyone = everyone_sid();
  LocalPtr keepalive_logon = logon_sid(base_token.get());
  LocalPtr workspace_sid;
  LocalPtr temp_sid;
  std::vector<PSID> restricting{keepalive_logon.get(), keepalive_everyone.get()};
  bool temp_granted = false;
  if (parsed.mode == L"workspace-write") {
    workspace_sid = sid_from_string(parsed.write_sid);
    temp_sid = sid_from_string(parsed.temp_write_sid);
    grant_write(parsed.workspace, workspace_sid.get());
    grant_write(parsed.temp, temp_sid.get());
    temp_granted = true;
    restricting.push_back(workspace_sid.get());
    restricting.push_back(temp_sid.get());
  }

  Handle restricted = create_restricted_token(base_token.get(), restricting);
  DWORD exit_code = 1;
  try {
    exit_code = run_child(restricted.get(), parsed.command);
  } catch (...) {
    if (temp_granted) revoke_write_best_effort(parsed.temp, temp_sid.get());
    throw;
  }
  if (temp_granted) revoke_write_best_effort(parsed.temp, temp_sid.get());
  return exit_code;
}
}  // namespace

int wmain(int argc, wchar_t** argv) {
  try {
    if (argc < 2 || std::wstring(argv[1]) != L"run") {
      fail("usage: newman-sandbox-win.exe run --workspace <dir> --temp <dir> --mode <mode> -- <argv...>");
    }
    return static_cast<int>(run(argc, argv));
  } catch (const RunnerFailure&) {
    return static_cast<int>(kRunnerFailureExit);
  } catch (const std::exception& exc) {
    std::cerr << "newman-windows-acl-run: " << exc.what() << "\n";
    return static_cast<int>(kRunnerFailureExit);
  }
}

#else

#include <iostream>
#include <string>

namespace {
constexpr int kRunnerFailureExit = 127;

void fail(const std::string& detail) {
  std::cerr << "newman-windows-acl-run: " << detail << "\n";
}
}  // namespace

int main(int argc, char** argv) {
  if (argc < 2 || std::string(argv[1]) != "run") {
    fail("usage: newman-sandbox-win.exe run --workspace <dir> --temp <dir> --mode <mode> -- <argv...>");
    return kRunnerFailureExit;
  }

  fail("windows ACL helper must be built on Windows");
  return kRunnerFailureExit;
}

#endif
