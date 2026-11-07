/** Client-side image prep for chat / agent attachments. */

export const MAX_EDGE = 1568; // larger images only cost prompt tokens; the model downsamples them anyway
const PASSTHROUGH_BYTES = 4 * 1024 * 1024;
const PASSTHROUGH_TYPES = ["image/png", "image/jpeg", "image/webp"];

export const isImageFile = (f: File) => f.type.startsWith("image/");
/** Documents the backend can read: PDF, Word, Excel, CSV/TSV, Markdown, plain text (browsers often report Markdown with an empty type). */
export const isDocFile = (f: File) => /\.(pdf|docx|xlsx|csv|tsv|md|markdown|txt)$/i.test(f.name) || ["application/pdf", "text/markdown", "text/plain", "text/csv"].includes(f.type);

function readAsDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(r.error ?? new Error("could not read the file"));
    r.readAsDataURL(blob);
  });
}

/** Returns a data URL: the original bytes when small enough, otherwise a downscaled JPEG (GIFs become their first frame). */
export async function prepareImage(file: File): Promise<string> {
  let bmp: ImageBitmap;
  try {
    bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    throw new Error(`“${file.name || "image"}” could not be decoded as an image`);
  }
  try {
    const small = Math.max(bmp.width, bmp.height) <= MAX_EDGE;
    if (small && file.size <= PASSTHROUGH_BYTES && PASSTHROUGH_TYPES.includes(file.type)) return await readAsDataUrl(file);
    const k = Math.min(1, MAX_EDGE / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bmp.width * k));
    canvas.height = Math.max(1, Math.round(bmp.height * k));
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("canvas is not available");
    ctx.fillStyle = "#fff"; // JPEG has no alpha
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.9);
  } finally {
    bmp.close();
  }
}
