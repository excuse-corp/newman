import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import UploadTaskPage from "./pages/UploadTaskPage";

function resolvePage() {
  const pathname = window.location.pathname.replace(/\/+$/, "") || "/";
  if (pathname === "/upload-task") {
    return UploadTaskPage;
  }
  return App;
}

const Page = resolvePage();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <Page />
  </React.StrictMode>
);
