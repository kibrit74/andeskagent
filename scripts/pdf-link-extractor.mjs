import fs from "node:fs/promises";
import path from "node:path";
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";

console.log = (...args) => {
  process.stderr.write(`${args.join(" ")}\n`);
};
console.info = (...args) => {
  process.stderr.write(`${args.join(" ")}\n`);
};
console.debug = (...args) => {
  process.stderr.write(`${args.join(" ")}\n`);
};

function normalizeString(value) {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.replace(/\s+/g, " ").trim();
  return trimmed || null;
}


function findNearestLabel(textItems, rect) {
  if (!Array.isArray(textItems) || textItems.length === 0 || !Array.isArray(rect) || rect.length < 4) {
    return null;
  }

  const [x1, y1, x2, y2] = rect.map((value) => Number(value) || 0);
  const centerX = (x1 + x2) / 2;
  const centerY = (y1 + y2) / 2;
  let best = null;

  for (const item of textItems) {
    const text = normalizeString(item?.str);
    if (!text || !Array.isArray(item?.transform)) {
      continue;
    }
    const itemX = Number(item.transform[4]) || 0;
    const itemY = Number(item.transform[5]) || 0;
    const distance = Math.abs(centerX - itemX) + Math.abs(centerY - itemY);
    if (!best || distance < best.distance) {
      best = { text, distance };
    }
  }

  return best?.text ?? null;
}


async function extractLinks(pdfPath, maxPages) {
  const resolvedPdfPath = path.resolve(pdfPath);
  const data = await fs.readFile(resolvedPdfPath);
  const loadingTask = getDocument({
    data: new Uint8Array(data),
    useWorkerFetch: false,
    isEvalSupported: false,
  });
  const pdf = await loadingTask.promise;
  const pageCount = Math.min(pdf.numPages, maxPages || pdf.numPages);
  const links = [];

  for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);
    const annotations = await page.getAnnotations();
    const textContent = await page.getTextContent();

    const pageText = Array.isArray(textContent?.items)
      ? textContent.items.map((item) => normalizeString(item?.str)).filter(Boolean).join(" ")
      : "";
    const urlMatches = pageText.match(/\bhttps?:\/\/[^\s)]+/gi) || [];

    for (const annotation of annotations) {
      if (annotation?.subtype !== "Link") {
        continue;
      }
      const url = normalizeString(annotation.url);
      const dest = annotation.dest ?? null;
      const rect = Array.isArray(annotation.rect) ? annotation.rect.map((value) => Number(value) || 0) : [];
      links.push({
        index: links.length,
        page_number: pageNumber,
        url,
        dest,
        title: normalizeString(annotation.title),
        contents: normalizeString(annotation.contents),
        label: findNearestLabel(textContent.items, rect) || url || normalizeString(annotation.title),
        rect,
      });
    }

    for (const rawUrl of urlMatches) {
      const cleanUrl = normalizeString(rawUrl);
      if (!cleanUrl) {
        continue;
      }
      if (links.some((link) => link.url === cleanUrl && link.page_number === pageNumber)) {
        continue;
      }
      links.push({
        index: links.length,
        page_number: pageNumber,
        url: cleanUrl,
        dest: null,
        title: null,
        contents: cleanUrl,
        label: cleanUrl,
        rect: [],
      });
    }
  }

  return {
    page_count: pdf.numPages,
    links,
  };
}


async function main() {
  const rawPayload = process.argv[2];
  if (!rawPayload) {
    throw new Error("JSON payload gerekli.");
  }

  const payload = JSON.parse(rawPayload);
  if (!payload.pdfPath) {
    throw new Error("pdfPath gerekli.");
  }

  const result = await extractLinks(payload.pdfPath, payload.maxPages);
  process.stdout.write(JSON.stringify(result, null, 2));
}


main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
