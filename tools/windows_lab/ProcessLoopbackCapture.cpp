// Minimal WASAPI process-loopback capture → WAV.
// Builds with VS 2022 cl.exe (see process_loopback.py _ensure_helper).
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <propvarutil.h>

#include <cstdio>
#include <cstdint>
#include <string>
#include <vector>
#include <atomic>

#pragma comment(lib, "Ole32.lib")
#pragma comment(lib, "Mmdevapi.lib")

namespace {

class CompletionHandler final : public IActivateAudioInterfaceCompletionHandler,
                                 public IAgileObject {
public:
  CompletionHandler() : ref_(1), hr_(E_FAIL), client_(nullptr) {
    event_ = CreateEventW(nullptr, FALSE, FALSE, nullptr);
  }
  ~CompletionHandler() {
    if (client_) client_->Release();
    if (event_) CloseHandle(event_);
  }

  HRESULT Wait(DWORD ms) {
    DWORD w = WaitForSingleObject(event_, ms);
    if (w != WAIT_OBJECT_0) return E_ABORT;
    return hr_;
  }
  IAudioClient* Client() const { return client_; }

  // IUnknown
  HRESULT STDMETHODCALLTYPE QueryInterface(REFIID riid, void** ppv) override {
    if (!ppv) return E_POINTER;
    *ppv = nullptr;
    if (riid == IID_IUnknown || riid == __uuidof(IActivateAudioInterfaceCompletionHandler)) {
      *ppv = static_cast<IActivateAudioInterfaceCompletionHandler*>(this);
      AddRef();
      return S_OK;
    }
    if (riid == IID_IAgileObject) {
      *ppv = static_cast<IAgileObject*>(this);
      AddRef();
      return S_OK;
    }
    return E_NOINTERFACE;
  }
  ULONG STDMETHODCALLTYPE AddRef() override { return ++ref_; }
  ULONG STDMETHODCALLTYPE Release() override {
    ULONG n = --ref_;
    if (n == 0) delete this;
    return n;
  }

  // IActivateAudioInterfaceCompletionHandler
  HRESULT STDMETHODCALLTYPE ActivateCompleted(IActivateAudioInterfaceAsyncOperation* op) override {
    HRESULT hrActivate = E_FAIL;
    IUnknown* unk = nullptr;
    HRESULT hr = op->GetActivateResult(&hrActivate, &unk);
    hr_ = FAILED(hr) ? hr : hrActivate;
    if (SUCCEEDED(hr_) && unk) {
      hr_ = unk->QueryInterface(IID_PPV_ARGS(&client_));
      unk->Release();
    }
    SetEvent(event_);
    return S_OK;
  }

private:
  std::atomic<ULONG> ref_;
  HRESULT hr_;
  IAudioClient* client_;
  HANDLE event_;
};

bool WriteWav(const wchar_t* path, const std::vector<uint8_t>& pcm, int rate, int ch, int bits) {
  // Ensure parent directory exists.
  {
    wchar_t dir[MAX_PATH];
    wcsncpy_s(dir, path, _TRUNCATE);
    wchar_t* slash = wcsrchr(dir, L'\\');
    if (!slash) slash = wcsrchr(dir, L'/');
    if (slash) {
      *slash = L'\0';
      CreateDirectoryW(dir, nullptr);
    }
  }
  FILE* f = nullptr;
  if (_wfopen_s(&f, path, L"wb") != 0 || !f) return false;
  const uint32_t dataSize = static_cast<uint32_t>(pcm.size());
  const uint16_t block = static_cast<uint16_t>(ch * bits / 8);
  const uint32_t byteRate = static_cast<uint32_t>(rate * block);
  fwrite("RIFF", 1, 4, f);
  uint32_t chunk = 36 + dataSize;
  fwrite(&chunk, 4, 1, f);
  fwrite("WAVEfmt ", 1, 8, f);
  uint32_t fmtSize = 16;
  fwrite(&fmtSize, 4, 1, f);
  uint16_t audioFormat = 1;
  fwrite(&audioFormat, 2, 1, f);
  uint16_t channels = static_cast<uint16_t>(ch);
  fwrite(&channels, 2, 1, f);
  uint32_t sampleRate = static_cast<uint32_t>(rate);
  fwrite(&sampleRate, 4, 1, f);
  fwrite(&byteRate, 4, 1, f);
  fwrite(&block, 2, 1, f);
  uint16_t bitsPer = static_cast<uint16_t>(bits);
  fwrite(&bitsPer, 2, 1, f);
  fwrite("data", 1, 4, f);
  fwrite(&dataSize, 4, 1, f);
  if (!pcm.empty()) fwrite(pcm.data(), 1, pcm.size(), f);
  fclose(f);
  return true;
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
  if (argc < 4) {
    fwprintf(stderr, L"usage: ProcessLoopbackCapture.exe <pid> <seconds> <out.wav>\n");
    return 2;
  }
  const DWORD pid = static_cast<DWORD>(_wtoi(argv[1]));
  const double seconds = _wtof(argv[2]);
  const wchar_t* outPath = argv[3];
  const int rate = 48000;
  const int channels = 2;
  const int bits = 16;

  HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
  if (FAILED(hr)) {
    fwprintf(stderr, L"CoInitializeEx failed 0x%08X\n", hr);
    return 1;
  }

  AUDIOCLIENT_ACTIVATION_PARAMS params{};
  params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
  params.ProcessLoopbackParams.TargetProcessId = pid;
  params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;

  PROPVARIANT activateParams{};
  activateParams.vt = VT_BLOB;
  activateParams.blob.cbSize = sizeof(params);
  activateParams.blob.pBlobData = reinterpret_cast<BYTE*>(&params);

  CompletionHandler* handler = new CompletionHandler();
  IActivateAudioInterfaceAsyncOperation* asyncOp = nullptr;
  hr = ActivateAudioInterfaceAsync(
      VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
      __uuidof(IAudioClient),
      &activateParams,
      handler,
      &asyncOp);
  if (FAILED(hr)) {
    fwprintf(stderr, L"ActivateAudioInterfaceAsync 0x%08X\n", hr);
    handler->Release();
    CoUninitialize();
    return 1;
  }
  hr = handler->Wait(15000);
  if (asyncOp) asyncOp->Release();
  if (FAILED(hr) || !handler->Client()) {
    fwprintf(stderr, L"activate result 0x%08X\n", hr);
    handler->Release();
    CoUninitialize();
    return 1;
  }

  IAudioClient* client = handler->Client();
  WAVEFORMATEX fmt{};
  fmt.wFormatTag = WAVE_FORMAT_PCM;
  fmt.nChannels = static_cast<WORD>(channels);
  fmt.nSamplesPerSec = rate;
  fmt.wBitsPerSample = static_cast<WORD>(bits);
  fmt.nBlockAlign = static_cast<WORD>(channels * bits / 8);
  fmt.nAvgBytesPerSec = rate * fmt.nBlockAlign;
  fmt.cbSize = 0;

  const DWORD streamFlags = AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK |
                            AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY;
  hr = client->Initialize(AUDCLNT_SHAREMODE_SHARED, streamFlags, 0, 0, &fmt, nullptr);
  if (FAILED(hr)) {
    fwprintf(stderr, L"Initialize 0x%08X\n", hr);
    handler->Release();
    CoUninitialize();
    return 1;
  }

  HANDLE ready = CreateEventW(nullptr, FALSE, FALSE, nullptr);
  hr = client->SetEventHandle(ready);
  if (FAILED(hr)) {
    fwprintf(stderr, L"SetEventHandle 0x%08X\n", hr);
    CloseHandle(ready);
    handler->Release();
    CoUninitialize();
    return 1;
  }

  IAudioCaptureClient* capture = nullptr;
  hr = client->GetService(__uuidof(IAudioCaptureClient), reinterpret_cast<void**>(&capture));
  if (FAILED(hr) || !capture) {
    fwprintf(stderr, L"GetService 0x%08X\n", hr);
    CloseHandle(ready);
    handler->Release();
    CoUninitialize();
    return 1;
  }

  std::vector<uint8_t> pcm;
  int peak = 0;
  uint64_t frames = 0;
  hr = client->Start();
  if (FAILED(hr)) {
    fwprintf(stderr, L"Start 0x%08X\n", hr);
    capture->Release();
    CloseHandle(ready);
    handler->Release();
    CoUninitialize();
    return 1;
  }

  const ULONGLONG t0 = GetTickCount64();
  const ULONGLONG limitMs = static_cast<ULONGLONG>(seconds * 1000.0);
  while (GetTickCount64() - t0 < limitMs) {
    WaitForSingleObject(ready, 200);
    UINT32 packet = 0;
    while (SUCCEEDED(capture->GetNextPacketSize(&packet)) && packet > 0) {
      BYTE* data = nullptr;
      UINT32 nFrames = 0;
      DWORD flags = 0;
      hr = capture->GetBuffer(&data, &nFrames, &flags, nullptr, nullptr);
      if (FAILED(hr)) break;
      const UINT32 nbytes = nFrames * fmt.nBlockAlign;
      const size_t old = pcm.size();
      pcm.resize(old + nbytes);
      if (data && !(flags & AUDCLNT_BUFFERFLAGS_SILENT)) {
        memcpy(pcm.data() + old, data, nbytes);
        const int16_t* s = reinterpret_cast<const int16_t*>(pcm.data() + old);
        const size_t nSamp = nbytes / 2;
        for (size_t i = 0; i < nSamp; ++i) {
          int a = s[i] < 0 ? -s[i] : s[i];
          if (a > peak) peak = a;
        }
      } else {
        memset(pcm.data() + old, 0, nbytes);
      }
      frames += nFrames;
      capture->ReleaseBuffer(nFrames);
    }
  }
  client->Stop();
  capture->Release();
  CloseHandle(ready);

  if (!WriteWav(outPath, pcm, rate, channels, bits)) {
    fwprintf(stderr, L"failed to write wav\n");
    handler->Release();
    CoUninitialize();
    return 1;
  }

  const double peakF = peak / 32768.0;
  // JSON on stdout for Python wrapper
  char pathUtf8[2048];
  WideCharToMultiByte(CP_UTF8, 0, outPath, -1, pathUtf8, sizeof(pathUtf8), nullptr, nullptr);
  // escape backslashes
  std::string esc;
  for (const char* p = pathUtf8; *p; ++p) {
    if (*p == '\\' || *p == '"') esc.push_back('\\');
    esc.push_back(*p);
  }
  printf("{\"ok\":true,\"pid\":%lu,\"seconds_requested\":%.3f,\"frames\":%llu,\"peak\":%.6f,\"wav\":\"%s\"}\n",
         static_cast<unsigned long>(pid), seconds, static_cast<unsigned long long>(frames), peakF, esc.c_str());

  handler->Release();
  CoUninitialize();
  return 0;
}
