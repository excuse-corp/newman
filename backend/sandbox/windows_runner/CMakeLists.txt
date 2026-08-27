cmake_minimum_required(VERSION 3.20)
project(newman_sandbox_win LANGUAGES CXX)

add_executable(newman-sandbox-win src/main.cpp)
target_compile_features(newman-sandbox-win PRIVATE cxx_std_20)

if(WIN32)
  target_link_libraries(newman-sandbox-win PRIVATE advapi32 bcrypt)
endif()
