export type LiveMarker = {
  type: "ad_start" | "content_start" | "note" | string;
  elapsed_seconds: number;
  wall_time: string;
  note: string | null;
};

export type AudioDevice = {
  index: number;
  name: string;
  max_input_channels: number;
  max_output_channels: number;
  default_samplerate: number;
};

export type OperatorMode = "pass_through" | "manual" | "auto";

export type LiveStatus = {
  recording: boolean;
  pipeline: "live" | "record" | null;
  standby: boolean;
  elapsed_seconds: number;
  dbfs: number;
  input_dbfs: number;
  output_dbfs: number;
  device_index: number | null;
  device_name: string | null;
  sample_rate_hz: number | null;
  channels: number | null;
  chunk: number;
  folder: string | null;
  session: string | null;
  markers: LiveMarker[];
  warnings_count: number;
  monitor_url: string | null;
  mode: OperatorMode | null;
  gate: "play" | "mute";
  gate_reason: string | null;
  transport: "stopped" | "priming" | "running";
  prime_ms: number;
  buffer_ms: number;
  buffer_frames: number;
  buffer_target_ms: number;
  buffer_min_ms: number | null;
  buffer_max_ms: number | null;
  input_device_name: string | null;
  output_device_name: string | null;
  input_device_index: number | null;
  output_device_index: number | null;
  input_channels: number | null;
  output_channels: number | null;
  input_rate_hz: number | null;
  output_rate_hz: number | null;
  input_default_rate_hz: number | null;
  output_default_rate_hz: number | null;
  requested_rate_hz: number;
  sample_rate_mismatch: boolean;
  host_resampling: boolean;
  input_portaudio_flags: number;
  output_portaudio_flags: number;
  ring_overruns: number;
  ring_underruns: number;
  record_queue_drops: number;
  reprime_count: number;
  xruns: number;
  recording_integrity: "ok" | "degraded";
  input_silent: boolean;
  input_disconnected: boolean;
  output_disconnected: boolean;
  engine_stalled: boolean;
  estimated_transport_latency_ms: number | null;
  input_stream_latency_ms: number | null;
  output_stream_latency_ms: number | null;
  near_zero_fraction: number;
  error: string | null;
  session_samples: number;
};

export const IDLE_STATUS: LiveStatus = {
  recording: false,
  pipeline: null,
  standby: false,
  elapsed_seconds: 0,
  dbfs: -100,
  input_dbfs: -100,
  output_dbfs: -100,
  device_index: null,
  device_name: null,
  sample_rate_hz: null,
  channels: null,
  chunk: 0,
  folder: null,
  session: null,
  markers: [],
  warnings_count: 0,
  monitor_url: null,
  mode: null,
  gate: "play",
  gate_reason: null,
  transport: "stopped",
  prime_ms: 40,
  buffer_ms: 0,
  buffer_frames: 0,
  buffer_target_ms: 40,
  buffer_min_ms: null,
  buffer_max_ms: null,
  input_device_name: null,
  output_device_name: null,
  input_device_index: null,
  output_device_index: null,
  input_channels: null,
  output_channels: null,
  input_rate_hz: null,
  output_rate_hz: null,
  input_default_rate_hz: null,
  output_default_rate_hz: null,
  requested_rate_hz: 48000,
  sample_rate_mismatch: false,
  host_resampling: false,
  input_portaudio_flags: 0,
  output_portaudio_flags: 0,
  ring_overruns: 0,
  ring_underruns: 0,
  record_queue_drops: 0,
  reprime_count: 0,
  xruns: 0,
  recording_integrity: "ok",
  input_silent: false,
  input_disconnected: false,
  output_disconnected: false,
  engine_stalled: false,
  estimated_transport_latency_ms: null,
  input_stream_latency_ms: null,
  output_stream_latency_ms: null,
  near_zero_fraction: 0,
  error: null,
  session_samples: 0,
};
