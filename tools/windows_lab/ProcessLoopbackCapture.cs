// WASAPI process loopback — capture one PID tree to WAV (no virtual cable).
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

namespace Ohush
{
    static class ProcessLoopbackCapture
    {
        const string ProcessLoopbackDevice = "VAD\\Process_Loopback";
        const int AudioClientActivationTypeProcessLoopback = 1;
        const int ProcessLoopbackModeIncludeTargetProcessTree = 0;
        const uint AudclntStreamflagsLoopback = 0x00020000;
        const uint AudclntStreamflagsEventcallback = 0x00040000;
        const uint AudclntStreamflagsAutoconvertpcm = 0x80000000;
        const uint AudclntStreamflagsSrcDefaultQuality = 0x08000000;
        const uint AudclntBufferflagsSilent = 0x2;
        const int AudclntSharemodeShared = 0;
        const ushort WaveFormatPcm = 1;
        const ushort VtBlob = 0x0041;

        static readonly Guid IID_IAudioClient = new Guid("1CB9DF46-9731-4E4B-A1CE-2156F124A0C6");
        static readonly Guid IID_IAudioCaptureClient = new Guid("C8AD25A1-998A-472A-B5B4-7674F3A6E8C0");

        [StructLayout(LayoutKind.Sequential)]
        struct WaveFormatEx
        {
            public ushort wFormatTag;
            public ushort nChannels;
            public uint nSamplesPerSec;
            public uint nAvgBytesPerSec;
            public ushort nBlockAlign;
            public ushort wBitsPerSample;
            public ushort cbSize;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct AudioClientProcessLoopbackParams
        {
            public uint TargetProcessId;
            public int ProcessLoopbackMode;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct AudioClientActivationParams
        {
            public int ActivationType;
            public AudioClientProcessLoopbackParams ProcessLoopbackParams;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct Blob
        {
            public uint cbSize;
            public IntPtr pBlobData;
        }

        // PROPVARIANT: vt + 3 reserved WORDs, then union at offset 8.
        [StructLayout(LayoutKind.Explicit, Size = 24)]
        struct PropVariant
        {
            [FieldOffset(0)] public ushort vt;
            [FieldOffset(2)] public ushort reserved1;
            [FieldOffset(4)] public ushort reserved2;
            [FieldOffset(6)] public ushort reserved3;
            [FieldOffset(8)] public Blob blob;
        }

        // Native object returned by ActivateAudioInterfaceAsync.
        [ComImport, Guid("72A22D78-CDE4-431D-B8CC-843A71199B6D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        public interface IActivateAudioInterfaceAsyncOperation
        {
            void GetActivateResult(out int activateResult, [MarshalAs(UnmanagedType.IUnknown)] out object activatedInterface);
        }

        // Managed (ComVisible) so QI for IAgileObject works on our handler.
        [ComVisible(true)]
        [Guid("41D949AB-9862-444A-80F6-C261334DA5EB")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        public interface IActivateAudioInterfaceCompletionHandler
        {
            void ActivateCompleted([MarshalAs(UnmanagedType.Interface)] IActivateAudioInterfaceAsyncOperation activateOperation);
        }

        [ComVisible(true)]
        [Guid("94EA2B94-E9CC-49CC-BC8B-512BD124A8A6")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        public interface IAgileObject
        {
        }

        [ComImport, Guid("C8AD25A1-998A-472A-B5B4-7674F3A6E8C0"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IAudioCaptureClient
        {
            void GetBuffer(out IntPtr data, out uint numFramesToRead, out uint flags, out ulong devicePosition, out ulong qpcPosition);
            void ReleaseBuffer(uint numFramesRead);
            void GetNextPacketSize(out uint numFramesInNextPacket);
        }

        [ComImport, Guid("1CB9DF46-9731-4E4B-A1CE-2156F124A0C6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IAudioClientFull
        {
            [PreserveSig] int Initialize(int shareMode, uint streamFlags, long hnsBufferDuration, long hnsPeriodicity, IntPtr pFormat, IntPtr audioSessionGuid);
            [PreserveSig] int GetBufferSize(out uint bufferFrameCount);
            [PreserveSig] int GetStreamLatency(out long latency);
            [PreserveSig] int GetCurrentPadding(out uint padding);
            [PreserveSig] int IsFormatSupported(int shareMode, IntPtr pFormat, out IntPtr ppClosestMatch);
            [PreserveSig] int GetMixFormat(out IntPtr ppDeviceFormat);
            [PreserveSig] int GetDevicePeriod(out long defaultDevicePeriod, out long minimumDevicePeriod);
            [PreserveSig] int Start();
            [PreserveSig] int Stop();
            [PreserveSig] int Reset();
            [PreserveSig] int SetEventHandle(IntPtr eventHandle);
            [PreserveSig] int GetService(ref Guid riid, [MarshalAs(UnmanagedType.IUnknown)] out object ppv);
        }

        [DllImport("Mmdevapi.dll", ExactSpelling = true, PreserveSig = true)]
        static extern int ActivateAudioInterfaceAsync(
            [MarshalAs(UnmanagedType.LPWStr)] string deviceInterfacePath,
            ref Guid riid,
            IntPtr activationParams,
            IActivateAudioInterfaceCompletionHandler completionHandler,
            out IActivateAudioInterfaceAsyncOperation activationOperation);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern IntPtr CreateEventW(IntPtr lpEventAttributes, bool bManualReset, bool bInitialState, string lpName);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool CloseHandle(IntPtr hObject);

        [DllImport("kernel32.dll")]
        static extern uint WaitForSingleObject(IntPtr hHandle, uint dwMilliseconds);

        static readonly Guid IID_IAgileObject = new Guid("94EA2B94-E9CC-49CC-BC8B-512BD124A8A6");
        static readonly Guid IID_IActivateHandler = new Guid("41D949AB-9862-444A-80F6-C261334DA5EB");

        [ComVisible(true)]
        [ClassInterface(ClassInterfaceType.None)]
        sealed class Handler : IActivateAudioInterfaceCompletionHandler, IAgileObject, ICustomQueryInterface
        {
            readonly ManualResetEventSlim _done = new ManualResetEventSlim(false);
            public int Hr;
            public object Client;

            public void ActivateCompleted(IActivateAudioInterfaceAsyncOperation op)
            {
                try
                {
                    object iface;
                    int hr;
                    op.GetActivateResult(out hr, out iface);
                    Hr = hr;
                    Client = iface;
                }
                catch
                {
                    Hr = unchecked((int)0x80004005);
                    Client = null;
                }
                finally
                {
                    _done.Set();
                }
            }

            public bool Wait(int ms)
            {
                return _done.Wait(ms);
            }

            // IAgileObject is a pure marker (IUnknown only). Empty managed interfaces
            // often fail QI; hand back this object's IUnknown for that IID.
            public CustomQueryInterfaceResult GetInterface(ref Guid iid, out IntPtr ppv)
            {
                if (iid == IID_IAgileObject)
                {
                    ppv = Marshal.GetIUnknownForObject(this);
                    return CustomQueryInterfaceResult.Handled;
                }
                ppv = IntPtr.Zero;
                return CustomQueryInterfaceResult.NotHandled;
            }
        }

        static int Main(string[] args)
        {
            if (args.Length < 3)
            {
                Console.Error.WriteLine("usage: ProcessLoopbackCapture.exe <pid> <seconds> <out.wav>");
                return 2;
            }

            // Ensure MTA for ActivateAudioInterfaceAsync.
            int result = 1;
            Exception caught = null;
            var t = new Thread(() =>
            {
                try
                {
                    result = Run(args);
                }
                catch (Exception ex)
                {
                    caught = ex;
                    result = 1;
                }
            });
            t.SetApartmentState(ApartmentState.MTA);
            t.Start();
            t.Join();
            if (caught != null)
            {
                Console.Error.WriteLine(caught.ToString());
                return 1;
            }
            return result;
        }

        static int Run(string[] args)
        {
            uint pid = uint.Parse(args[0]);
            double seconds = double.Parse(args[1], System.Globalization.CultureInfo.InvariantCulture);
            string outPath = args[2];
            int rate = 48000;
            int channels = 2;
            int bits = 16;

            var act = new AudioClientActivationParams
            {
                ActivationType = AudioClientActivationTypeProcessLoopback,
                ProcessLoopbackParams = new AudioClientProcessLoopbackParams
                {
                    TargetProcessId = pid,
                    ProcessLoopbackMode = ProcessLoopbackModeIncludeTargetProcessTree
                }
            };
            int actSize = Marshal.SizeOf(typeof(AudioClientActivationParams));
            IntPtr actPtr = Marshal.AllocHGlobal(actSize);
            try
            {
                Marshal.StructureToPtr(act, actPtr, false);
                var prop = new PropVariant();
                prop.vt = VtBlob;
                prop.blob = new Blob { cbSize = (uint)actSize, pBlobData = actPtr };
                IntPtr propPtr = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(PropVariant)));
                try
                {
                    Marshal.StructureToPtr(prop, propPtr, false);
                    var handler = new Handler();
                    var iid = IID_IAudioClient;
                    IActivateAudioInterfaceAsyncOperation op;
                    int hr = ActivateAudioInterfaceAsync(ProcessLoopbackDevice, ref iid, propPtr, handler, out op);
                    if (hr < 0)
                        throw new Exception(string.Format("ActivateAudioInterfaceAsync 0x{0:X8}", hr));
                    if (!handler.Wait(15000))
                        throw new Exception("activation timeout");
                    if (handler.Hr < 0 || handler.Client == null)
                        throw new Exception(string.Format("activate result 0x{0:X8}", handler.Hr));

                    var client = (IAudioClientFull)handler.Client;
                    var fmt = new WaveFormatEx
                    {
                        wFormatTag = WaveFormatPcm,
                        nChannels = (ushort)channels,
                        nSamplesPerSec = (uint)rate,
                        wBitsPerSample = (ushort)bits,
                        nBlockAlign = (ushort)(channels * bits / 8),
                        nAvgBytesPerSec = (uint)(rate * channels * bits / 8),
                        cbSize = 0
                    };
                    IntPtr fmtPtr = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(WaveFormatEx)));
                    try
                    {
                        Marshal.StructureToPtr(fmt, fmtPtr, false);
                        uint streamFlags = AudclntStreamflagsLoopback | AudclntStreamflagsEventcallback
                            | AudclntStreamflagsAutoconvertpcm | AudclntStreamflagsSrcDefaultQuality;
                        hr = client.Initialize(AudclntSharemodeShared, streamFlags, 0, 0, fmtPtr, IntPtr.Zero);
                        if (hr < 0)
                            throw new Exception(string.Format("Initialize 0x{0:X8}", hr));

                        IntPtr ev = CreateEventW(IntPtr.Zero, false, false, null);
                        if (ev == IntPtr.Zero)
                            throw new Exception("CreateEvent failed");
                        try
                        {
                            hr = client.SetEventHandle(ev);
                            if (hr < 0)
                                throw new Exception(string.Format("SetEventHandle 0x{0:X8}", hr));
                            var capIid = IID_IAudioCaptureClient;
                            object capObj;
                            hr = client.GetService(ref capIid, out capObj);
                            if (hr < 0 || capObj == null)
                                throw new Exception(string.Format("GetService 0x{0:X8}", hr));
                            var capture = (IAudioCaptureClient)capObj;

                            using (var ms = new MemoryStream())
                            {
                                int peak = 0;
                                long frames = 0;
                                hr = client.Start();
                                if (hr < 0)
                                    throw new Exception(string.Format("Start 0x{0:X8}", hr));
                                var sw = System.Diagnostics.Stopwatch.StartNew();
                                try
                                {
                                    while (sw.Elapsed.TotalSeconds < seconds)
                                    {
                                        WaitForSingleObject(ev, 200);
                                        while (true)
                                        {
                                            uint packet;
                                            capture.GetNextPacketSize(out packet);
                                            if (packet == 0) break;
                                            IntPtr data;
                                            uint nRead, flags;
                                            ulong devPos, qpc;
                                            capture.GetBuffer(out data, out nRead, out flags, out devPos, out qpc);
                                            int nbytes = (int)(nRead * fmt.nBlockAlign);
                                            byte[] buf = new byte[nbytes];
                                            if (data != IntPtr.Zero && nbytes > 0 && (flags & AudclntBufferflagsSilent) == 0)
                                                Marshal.Copy(data, buf, 0, nbytes);
                                            for (int i = 0; i + 1 < buf.Length; i += 2)
                                            {
                                                short s = (short)(buf[i] | (buf[i + 1] << 8));
                                                int a = Math.Abs((int)s);
                                                if (a > peak) peak = a;
                                            }
                                            ms.Write(buf, 0, buf.Length);
                                            frames += nRead;
                                            capture.ReleaseBuffer(nRead);
                                        }
                                    }
                                }
                                finally
                                {
                                    client.Stop();
                                }

                                string dir = Path.GetDirectoryName(Path.GetFullPath(outPath));
                                if (!string.IsNullOrEmpty(dir))
                                    Directory.CreateDirectory(dir);
                                WriteWav(outPath, ms.ToArray(), rate, channels, bits);
                                double peakF = peak / 32768.0;
                                Console.WriteLine(
                                    "{{\"ok\":true,\"pid\":{0},\"seconds_requested\":{1},\"frames\":{2},\"peak\":{3},\"wav\":{4}}}",
                                    pid,
                                    seconds.ToString(System.Globalization.CultureInfo.InvariantCulture),
                                    frames,
                                    peakF.ToString("0.######", System.Globalization.CultureInfo.InvariantCulture),
                                    ToJsonString(Path.GetFullPath(outPath)));
                            }
                        }
                        finally
                        {
                            CloseHandle(ev);
                        }
                    }
                    finally
                    {
                        Marshal.FreeHGlobal(fmtPtr);
                    }
                }
                finally
                {
                    Marshal.FreeHGlobal(propPtr);
                }
            }
            finally
            {
                Marshal.FreeHGlobal(actPtr);
            }
            return 0;
        }

        static string ToJsonString(string s)
        {
            return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
        }

        static void WriteWav(string path, byte[] pcm, int rate, int channels, int bits)
        {
            using (var fs = File.Create(path))
            using (var bw = new BinaryWriter(fs))
            {
                int dataSize = pcm.Length;
                int byteRate = rate * channels * bits / 8;
                short blockAlign = (short)(channels * bits / 8);
                bw.Write(System.Text.Encoding.ASCII.GetBytes("RIFF"));
                bw.Write(36 + dataSize);
                bw.Write(System.Text.Encoding.ASCII.GetBytes("WAVE"));
                bw.Write(System.Text.Encoding.ASCII.GetBytes("fmt "));
                bw.Write(16);
                bw.Write((short)1);
                bw.Write((short)channels);
                bw.Write(rate);
                bw.Write(byteRate);
                bw.Write(blockAlign);
                bw.Write((short)bits);
                bw.Write(System.Text.Encoding.ASCII.GetBytes("data"));
                bw.Write(dataSize);
                bw.Write(pcm);
            }
        }
    }
}
