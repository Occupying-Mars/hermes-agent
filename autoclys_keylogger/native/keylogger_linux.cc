#ifdef __linux__

#include <napi.h>

void StartKeyloggerLinux(const Napi::CallbackInfo& info) {
  Napi::Error::New(info.Env(), "autoclys observation keylogger is not implemented for linux yet")
      .ThrowAsJavaScriptException();
}

void StopKeyloggerLinux(const Napi::CallbackInfo& info) {
  (void)info;
}

Napi::String GetActiveWindowLinux(const Napi::CallbackInfo& info) {
  return Napi::String::New(info.Env(), "unsupported");
}

#endif
