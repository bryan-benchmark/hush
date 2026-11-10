import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";
import { farmCloudMode } from "@/lib/farmAccess";
import { farmCloudAudio } from "@/lib/farmCloud";

export const runtime = "nodejs";

function extractWavSlice(wavPath: string, startSec: number, durationSec: number): Buffer {
  const fd = fs.openSync(wavPath, "r");
  try {
    const header = Buffer.alloc(44);
    fs.readSync(fd, header, 0, 44, 0);
    if (header.toString("ascii", 0, 4) !== "RIFF") throw new Error("not a RIFF wav");
    const channels = header.readUInt16LE(22);
    const rate = header.readUInt32LE(24);
    const bits = header.readUInt16LE(34);
    if (bits !== 16) throw new Error(`unsupported bits: ${bits}`);

    let dataOffset = 44;
    let pos = 12;
    const stat = fs.fstatSync(fd);
    const probe = Buffer.alloc(Math.min(stat.size, 2048));
    fs.readSync(fd, probe, 0, probe.length, 0);
    while (pos + 8 <= probe.length) {
      const id = probe.toString("ascii", pos, pos + 4);
      const size = probe.readUInt32LE(pos + 4);
      if (id === "data") {
        dataOffset = pos + 8;
        break;
      }
      pos += 8 + size + (size % 2);
    }

    const bytesPerFrame = channels * 2;
    const startFrame = Math.max(0, Math.floor(startSec * rate));
    const nFrames = Math.max(1, Math.floor(durationSec * rate));
    const startByte = dataOffset + startFrame * bytesPerFrame;
    const wantBytes = nFrames * bytesPerFrame;
    const available = Math.max(0, stat.size - startByte);
    const readBytes = Math.min(wantBytes, available - (available % bytesPerFrame));
    const pcm = Buffer.alloc(readBytes);
    if (readBytes > 0) fs.readSync(fd, pcm, 0, readBytes, startByte);

    const frames = readBytes / bytesPerFrame;
    const mono = Buffer.alloc(frames * 2);
    for (let i = 0; i < frames; i++) {
      if (channels === 1) {
        mono.writeInt16LE(pcm.readInt16LE(i * 2), i * 2);
      } else {
        const l = pcm.readInt16LE(i * bytesPerFrame);
        const r = pcm.readInt16LE(i * bytesPerFrame + 2);
        mono.writeInt16LE(((l + r) / 2) | 0, i * 2);
      }
    }

    const dataSize = mono.length;
    const out = Buffer.alloc(44 + dataSize);
    out.write("RIFF", 0);
    out.writeUInt32LE(36 + dataSize, 4);
    out.write("WAVE", 8);
    out.write("fmt ", 12);
    out.writeUInt32LE(16, 16);
    out.writeUInt16LE(1, 20);
    out.writeUInt16LE(1, 22);
    out.writeUInt32LE(rate, 24);
    out.writeUInt32LE(rate * 2, 28);
    out.writeUInt16LE(2, 32);
    out.writeUInt16LE(16, 34);
    out.write("data", 36);
    out.writeUInt32LE(dataSize, 40);
    mono.copy(out, 44);
    return out;
  } finally {
    fs.closeSync(fd);
  }
}

function allowedFarmPath(p: string) {
  const root = path.resolve(process.env.OHUSH_DATA_ROOT || "C:\\OHushData");
  const resolved = path.resolve(p);
  return resolved === root || resolved.startsWith(root + path.sep);
}

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const id = sp.get("id") || "";
  if ((farmCloudMode() || id) && id) {
    try {
      const buf = await farmCloudAudio(id);
      if (!buf) return NextResponse.json({ error: "wav not found" }, { status: 404 });
      return new NextResponse(buf, {
        status: 200,
        headers: { "Content-Type": "audio/wav", "Cache-Control": "no-store" },
      });
    } catch (err) {
      return NextResponse.json({ error: String(err) }, { status: 500 });
    }
  }

  const sessionDir = sp.get("session_dir") || "";
  const audioRel = sp.get("audio_rel") || "audio.wav";
  const start = Number(sp.get("start") || "0");
  const duration = Number(sp.get("duration") || "12");
  if (!sessionDir) {
    return NextResponse.json({ error: "session_dir or id required" }, { status: 400 });
  }
  if (!allowedFarmPath(sessionDir)) {
    return NextResponse.json({ error: "session_dir outside data root" }, { status: 403 });
  }
  const wavPath = path.join(sessionDir, audioRel);
  if (!fs.existsSync(wavPath)) {
    return NextResponse.json({ error: "wav not found" }, { status: 404 });
  }
  try {
    const buf = extractWavSlice(wavPath, start, duration);
    return new NextResponse(buf, {
      status: 200,
      headers: {
        "Content-Type": "audio/wav",
        "Cache-Control": "no-store",
      },
    });
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 });
  }
}
