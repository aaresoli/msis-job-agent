/** Server-sent-event framing for the coach stream.
 *
 * Lives here rather than in the page so the framing rules can be tested
 * directly: the bugs this replaces were all boundary conditions that a
 * fast local model never reproduces by hand.
 */

/** Yield complete SSE frames, holding back any partial trailing frame.
 *
 * A frame is only whole once its blank-line terminator has arrived. Decoding
 * each network chunk in isolation dropped every frame that happened to straddle
 * a chunk boundary, which is invisible on a fast local model and common under
 * load. `stream: true` matters for the same reason one level down: a multi-byte
 * character split across chunks decodes to a replacement character otherwise.
 */
export async function* sseFrames(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      yield buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
  }
  // Flush any trailing multi-byte sequence, then any frame the server sent
  // without a terminator before closing.
  buffer += decoder.decode();
  if (buffer.trim()) yield buffer;
}

/** Parse a frame's `data:` payload, or undefined when it has none. */
export function frameData(frame: string): unknown {
  const line = frame.split("\n").find((part) => part.startsWith("data: "));
  if (!line) return undefined;
  try {
    return JSON.parse(line.slice(6));
  } catch {
    return undefined;
  }
}
