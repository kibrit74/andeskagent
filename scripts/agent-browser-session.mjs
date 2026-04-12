import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { pathToFileURL } from "node:url";


const DEFAULT_TIMEOUT_MS = 15000;
const sessions = new Map();


function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}


function inferMode(url) {
  if (!url) {
    return "web";
  }
  if (url.startsWith("file:") && url.toLowerCase().endsWith(".pdf")) {
    return "document";
  }
  return "web";
}


async function getPrimaryPage(context) {
  const pages = context.pages();
  if (pages.length > 0) {
    return pages[0];
  }
  return context.newPage();
}


async function summarizeSession(sessionId, entry, extra = {}) {
  const page = entry ? await getPrimaryPage(entry.context) : null;
  const url = page ? page.url() : null;
  const title = page ? await page.title().catch(() => null) : null;
  return {
    session_id: sessionId,
    title,
    url,
    page_count: entry ? entry.context.pages().length : 0,
    mode: entry ? entry.mode || inferMode(url) : "web",
    user_data_dir: entry ? entry.userDataDir : "",
    ...extra,
  };
}


async function ensureSession(sessionId, userDataDir) {
  let entry = sessions.get(sessionId);
  if (entry) {
    return { entry, reused: true };
  }

  const resolvedUserDataDir = path.resolve(userDataDir);
  ensureDir(resolvedUserDataDir);

  const context = await chromium.launchPersistentContext(resolvedUserDataDir, {
    headless: false,
    viewport: { width: 1365, height: 900 },
    acceptDownloads: true,
    args: [
      "--disable-background-networking",
      "--disable-default-apps",
      "--disable-extensions",
      "--disable-features=OverlayScrollbar",
      "--disable-sync",
      "--no-first-run",
      "--password-store=basic",
    ],
  });

  context.setDefaultTimeout(DEFAULT_TIMEOUT_MS);
  const page = await getPrimaryPage(context);
  entry = {
    sessionId,
    userDataDir: resolvedUserDataDir,
    context,
    page,
    mode: "web",
  };
  sessions.set(sessionId, entry);
  return { entry, reused: false };
}


async function navigatePage(page, url) {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.bringToFront().catch(() => {});
  await page.evaluate(() => window.focus()).catch(() => {});
  await page.focus("body").catch(() => {});
}


async function handleRequest(request) {
  const action = request?.action;
  if (!action) {
    throw new Error("Action gerekli.");
  }

  if (action === "shutdown") {
    for (const entry of sessions.values()) {
      await entry.context.close().catch(() => {});
    }
    sessions.clear();
    return { shutting_down: true };
  }

  if (action === "session_info") {
    const entry = sessions.get(request.sessionId || "browser-main");
    if (!entry) {
      return {
        session_id: request.sessionId || "browser-main",
        title: null,
        url: null,
        page_count: 0,
        mode: "web",
        user_data_dir: "",
        opened: false,
      };
    }
    return summarizeSession(request.sessionId || "browser-main", entry, {
      opened: true,
      reused: true,
    });
  }

  if (action === "close_session") {
    const existingEntry = sessions.get(request.sessionId || "browser-main");
    if (!existingEntry) {
      return {
        session_id: request.sessionId || "browser-main",
        title: null,
        url: null,
        page_count: 0,
        mode: "web",
        user_data_dir: "",
        closed: false,
      };
    }
    await existingEntry.context.close();
    sessions.delete(request.sessionId || "browser-main");
    return {
      session_id: request.sessionId || "browser-main",
      title: null,
      url: null,
      page_count: 0,
      mode: "web",
      user_data_dir: existingEntry.userDataDir,
      closed: true,
    };
  }

  const sessionId = request.sessionId || "browser-main";
  const userDataDir = request.userDataDir || path.resolve("data", "agent-browser", sessionId);
  const { entry, reused } = await ensureSession(sessionId, userDataDir);
  const page = await getPrimaryPage(entry.context);
  entry.page = page;

  if (action === "open_session") {
    if (request.targetUrl) {
      await navigatePage(page, request.targetUrl);
      entry.mode = inferMode(page.url());
    }
    return summarizeSession(sessionId, entry, {
      opened: true,
      reused,
      loaded: Boolean(request.targetUrl),
    });
  }

  if (action === "navigate") {
    if (!request.url) {
      throw new Error("Navigate icin url gerekli.");
    }
    await navigatePage(page, request.url);
    entry.mode = inferMode(page.url());
    return summarizeSession(sessionId, entry, {
      opened: true,
      reused,
      loaded: true,
    });
  }

  if (action === "open_document") {
    if (!request.filePath) {
      throw new Error("Dokuman acmak icin filePath gerekli.");
    }
    const resolvedPath = path.resolve(request.filePath);
    if (!fs.existsSync(resolvedPath)) {
      throw new Error(`Dosya bulunamadi: ${resolvedPath}`);
    }
    const fileUrl = pathToFileURL(resolvedPath).href;
    await navigatePage(page, fileUrl);
    entry.mode = inferMode(fileUrl);
    return summarizeSession(sessionId, entry, {
      opened: true,
      reused,
      loaded: true,
    });
  }

  throw new Error(`Bilinmeyen action: ${action}`);
}


function writeResponse(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}


async function runServeMode() {
  const rl = readline.createInterface({
    input: process.stdin,
    crlfDelay: Infinity,
  });

  for await (const line of rl) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }

    try {
      const request = JSON.parse(trimmed);
      const result = await handleRequest(request);
      writeResponse({ ok: true, result });
      if (request.action === "shutdown") {
        process.exit(0);
      }
    } catch (error) {
      writeResponse({
        ok: false,
        error: error instanceof Error ? error.message : String(error),
        code: "AGENT_BROWSER_REQUEST_FAILED",
      });
    }
  }
}


async function runCliMode() {
  const rawPayload = process.argv[2];
  if (!rawPayload) {
    throw new Error("JSON payload gerekli.");
  }
  const request = JSON.parse(rawPayload);
  const result = await handleRequest(request);
  process.stdout.write(JSON.stringify(result, null, 2));
}


if (process.argv.includes("--serve")) {
  runServeMode().catch((error) => {
    writeResponse({
      ok: false,
      error: error instanceof Error ? error.message : String(error),
      code: "AGENT_BROWSER_FATAL",
    });
    process.exit(1);
  });
} else {
  runCliMode().catch((error) => {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    process.exit(1);
  });
}
