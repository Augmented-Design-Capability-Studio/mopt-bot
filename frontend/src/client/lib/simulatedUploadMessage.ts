/** Matches `simulateUpload` / researcher push dummy upload user messages. */
export const SIMULATED_UPLOAD_MESSAGE_PREFIX = "I'm uploading the following file(s): ";

export function buildSimulatedUploadMessage(fileNames: string[]): string {
  return `${SIMULATED_UPLOAD_MESSAGE_PREFIX}${fileNames.join(", ")}`;
}

export function parseFilenamesFromSimulatedUploadMessage(content: string): string[] | null {
  if (!content.startsWith(SIMULATED_UPLOAD_MESSAGE_PREFIX)) return null;
  return content
    .slice(SIMULATED_UPLOAD_MESSAGE_PREFIX.length)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}
