// Executed by chrome-devtools-axi run against the real connected web/Identity pair.
const results = [];
for (const locale of ["en", "ar"])
  for (const theme of ["light", "dark"]) {
    await page.eval(
      `document.cookie='bt-theme=${theme}; Path=/; SameSite=Lax'`,
    );
    const navigation = await page.open(
      `http://localhost:3202/${locale}/business`,
    );
    await page.wait(".business-card");
    const result = await page.eval(() => ({
      url: location.pathname,
      width: innerWidth,
      height: innerHeight,
      dpr: devicePixelRatio,
      locale: document.documentElement.lang,
      dir: document.documentElement.dir,
      theme: document.documentElement.dataset.theme,
      documentWidth: document.documentElement.scrollWidth,
      title: document.querySelector("h1")?.textContent,
      cards: [...document.querySelectorAll(".business-card")].map((card) => ({
        title: card.querySelector("h2")?.textContent,
        sample: card.querySelector(".business-badge")?.textContent,
      })),
      background: getComputedStyle(document.querySelector(".business-card"))
        .backgroundColor,
      clippedContent: [
        ...document.querySelectorAll(
          ".business-heading,.business-heading p,.business-grid,.business-card,.business-card h2,.business-card p",
        ),
      ]
        .filter((element) => element.scrollWidth > element.clientWidth + 1)
        .map((element) => element.className || element.tagName),
      smallTargets: [...document.querySelectorAll("main a,main button")]
        .filter((element) => {
          const box = element.getBoundingClientRect();
          return box.height > 0 && (box.width < 43.5 || box.height < 43.5);
        })
        .map((element) => element.textContent),
      forbiddenApplication: !!document.querySelector(
        'input[name="legal_name"]',
      ),
    }));
    if (
      navigation.status !== 200 ||
      result.theme !== theme ||
      result.dir !== (locale === "ar" ? "rtl" : "ltr") ||
      result.documentWidth > result.width + 1 ||
      result.cards.length !== 2 ||
      result.smallTargets.length ||
      result.clippedContent.length ||
      result.forbiddenApplication
    )
      throw new Error("Public browser proof failed: " + JSON.stringify(result));
    results.push(result);
  }
console.log(JSON.stringify(results, null, 2));
