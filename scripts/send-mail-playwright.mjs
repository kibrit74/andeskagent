import { chromium } from "playwright";

function fail(message) {
  process.stdout.write(JSON.stringify({ status: "error", message: message }));
  process.exit(0); // Exit gracefully so adapter can read the JSON cleanly without throw.
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForGmail(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const url = page.url();
    if (url.includes("accounts.google.com")) {
      process.stdout.write(JSON.stringify({ status: "auth_required", code: "GMAIL_LOGIN_REQUIRED", message: "Gmail oturumu acik degil." }));
      process.exit(0);
    }
    if (url.includes("mail.google.com")) {
      return;
    }
    await wait(1000);
  }
  process.stdout.write(JSON.stringify({ status: "auth_required", code: "GMAIL_LOGIN_REQUIRED", message: "Gmail oturumu acik degil." }));
  process.exit(0);
}

function buildComposeUrl(payload) {
  const url = new URL(payload.mailUrl || "https://mail.google.com/mail/u/0/#inbox");
  url.searchParams.set("view", "cm");
  url.searchParams.set("fs", "1");
  if ((payload.to || []).length) {
    url.searchParams.set("to", payload.to.join(","));
  }
  if (payload.subject) {
    url.searchParams.set("su", payload.subject);
  }
  if (payload.body) {
    url.searchParams.set("body", payload.body);
  }
  return url.toString();
}

async function fillRecipients(dialog, recipients) {
  const target = dialog.locator('input[aria-label*="To"], textarea[name="to"], input[role="combobox"]').first();
  await target.waitFor({ timeout: 15000 });
  await target.click();
  const currentValue = await target.inputValue().catch(() => "");
  if (!currentValue.trim()) {
    await target.fill(recipients.join(", "));
  }
}

async function fillSubject(dialog, subject) {
  const locator = dialog.locator('input[name="subjectbox"]').first();
  await locator.waitFor({ timeout: 15000 });
  await locator.fill(subject);
}

async function fillBody(dialog, body) {
  const locator = dialog.locator('div[role="textbox"][aria-label]').last();
  await locator.waitFor({ timeout: 15000 });
  await locator.click();
  await locator.fill(body);
}

async function attachFiles(dialog, attachments) {
  if (!attachments.length) {
    return;
  }
  const fileInput = dialog.locator('input[type="file"]').last();
  await fileInput.setInputFiles(attachments);
  await wait(3000);
}

async function sendMessage(dialog, page) {
  const selectors = [
    'div[role="button"][data-tooltip^="Send"]',
    'div[role="button"][data-tooltip^="Gönder"]',
    'div[role="button"][aria-label*="Send"]',
    'div[role="button"][aria-label*="Gönder"]',
  ];

  for (const selector of selectors) {
    const locator = dialog.locator(selector).first();
    if (await locator.count()) {
      await locator.click({ timeout: 10000 });
      await wait(3000);
      return;
    }
  }

  await page.keyboard.press("Control+Enter");
  await wait(3000);

  const sentBanner = page.locator('span[data-tooltip*="Message sent"], span[data-tooltip*="Mesaj gonderildi"], div[role="alert"]').first();
  if (await sentBanner.count()) {
    return;
  }
  process.stdout.write(JSON.stringify({ status: "session_error", code: "GMAIL_SEND_NOT_CONFIRMED", message: "Gmail gonderim islemi dogrulanamadi." }));
  process.exit(0);
}

async function main() {
  const raw = process.argv[2];
  if (!raw) {
    fail("Mail payload missing.");
  }

  const payload = JSON.parse(raw);
  const launchOptions = {
    headless: Boolean(payload.headless),
    viewport: { width: 1440, height: 960 },
    locale: "tr-TR",
    timezoneId: "Europe/Istanbul",
    userAgent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    ignoreDefaultArgs: ["--enable-automation"],
  };
  if (payload.browserChannel && payload.browserChannel !== "chromium") {
    launchOptions.channel = payload.browserChannel;
  }
  const context = await chromium.launchPersistentContext(payload.userDataDir, launchOptions);

  try {
    const page = context.pages()[0] || await context.newPage();
    await page.goto(payload.mailUrl || "https://mail.google.com/mail/u/0/#inbox", {
      waitUntil: "domcontentloaded",
      timeout: 120000,
    });

    await waitForGmail(page, 120000);
    await page.goto(buildComposeUrl(payload), {
      waitUntil: "domcontentloaded",
      timeout: 120000,
    });

    if (page.url().includes("accounts.google.com")) {
      process.stdout.write(JSON.stringify({ status: "auth_required", code: "GMAIL_LOGIN_REQUIRED", message: "Gmail oturumu acik degil." }));
      process.exit(0);
    }

    const dialog = page.locator('div[role="dialog"]').last();
    try {
      await dialog.waitFor({ timeout: 15000 });
    } catch {
      process.stdout.write(JSON.stringify({ status: "session_error", code: "GMAIL_COMPOSE_NOT_READY", message: "Gmail yazma penceresi acilamadi." }));
      process.exit(0);
    }

    await fillRecipients(dialog, payload.to || []);
    await fillSubject(dialog, payload.subject || "");
    await fillBody(dialog, payload.body || "");
    await attachFiles(dialog, payload.attachments || []);
    await sendMessage(dialog, page);

    process.stdout.write(
      JSON.stringify({
        sent_to: payload.to || [],
        subject: payload.subject || "",
        status: "sent",
      }),
    );
  } finally {
    await context.close();
  }
}

main().catch((error) => fail(error instanceof Error ? error.message : String(error)));
