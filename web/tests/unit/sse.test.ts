import { describe, expect, it } from "vitest";

import { frameData, sseFrames } from "../../lib/sse";

/** A stream that hands back exactly the chunks given, boundaries included. */
function streamOf(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

const encode = (text: string) => new TextEncoder().encode(text);

async function collect(stream: ReadableStream<Uint8Array>): Promise<string[]> {
  const frames: string[] = [];
  for await (const frame of sseFrames(stream)) frames.push(frame);
  return frames;
}

describe("sseFrames", () => {
  it("keeps a frame that arrives split across two reads", async () => {
    // The old reader split each chunk on its own, so the half-frames on either
    // side of this boundary were both discarded and the token vanished.
    const frames = await collect(
      streamOf([encode('event: token\ndata: {"te'), encode('xt":"hello"}\n\n')]),
    );

    expect(frames).toHaveLength(1);
    expect(frameData(frames[0])).toEqual({ text: "hello" });
  });

  it("separates several frames delivered in one read", async () => {
    const frames = await collect(
      streamOf([
        encode(
          'event: token\ndata: {"text":"a"}\n\nevent: token\ndata: {"text":"b"}\n\n',
        ),
      ]),
    );

    expect(frames.map((frame) => (frameData(frame) as { text: string }).text)).toEqual([
      "a",
      "b",
    ]);
  });

  it("decodes a multi-byte character split across reads", async () => {
    // "—" is three bytes; cutting it in half produced a replacement character
    // in the student's answer.
    const payload = encode('event: token\ndata: {"text":"a—b"}\n\n');
    const frames = await collect(
      streamOf([payload.slice(0, 22), payload.slice(22)]),
    );

    expect(frameData(frames[0])).toEqual({ text: "a—b" });
  });

  it("emits the done frame with its truncated flag", async () => {
    const frames = await collect(
      streamOf([encode('event: done\ndata: {"truncated":true}\n\n')]),
    );

    expect(frameData(frames[0])).toEqual({ truncated: true });
  });

  it("yields a final frame the server never terminated", async () => {
    const frames = await collect(
      streamOf([encode('event: token\ndata: {"text":"tail"}')]),
    );

    expect(frameData(frames[0])).toEqual({ text: "tail" });
  });
});

describe("frameData", () => {
  it("returns undefined rather than throwing on an unparsable frame", () => {
    expect(frameData("event: token\ndata: {broken")).toBeUndefined();
    expect(frameData("event: ping")).toBeUndefined();
  });
});
