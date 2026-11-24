// 构建后执行：node script/fund_page_test.cjs；只替换测试页面响应，不改真实数据。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

async function main() {
  const browser = await chromium.launch({ headless: true, channel: "msedge" });
  const html = fs.readFileSync(path.join(__dirname, "../_site/fund/index.html"), "utf8");
  async function check(snapshots, expected, viewport = { width: 1366, height: 900 }) {
    const page = await browser.newPage({ viewport });
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/fund/", route => {
      const source = snapshots ? html.replace(
        /window\.FUND_DATA\s*=\s*[\s\S]*?<\/script>/,
        `window.FUND_DATA = ${JSON.stringify({
          funds: [{ id: "test", name: "测试基金", channel: "场内", tracking: "测试", venue: "场内", platform: "测试" }],
          snapshots,
          meta: { title: "测试" }
        })};</script>`
      ) : html;
      return route.fulfill({ contentType: "text/html; charset=utf-8", body: source });
    });
    try {
      await page.goto("http://127.0.0.1:4001/fund/");
      await page.waitForSelector("#fdStats .fd-stat");
      const stats = await page.locator("#fdStats .fd-stat").evaluateAll(cards =>
        Object.fromEntries(cards.map(card => [
          card.querySelector(".fd-stat-label").textContent,
          card.querySelector(".fd-stat-value").textContent
        ]))
      );
      for (const [label, amount] of Object.entries(expected)) assert.equal(stats[label], amount);
      assert.equal(stats["累计收益率"], undefined);
      assert.deepEqual(errors, []);
      assert.equal(await page.evaluate(() =>
        document.documentElement.scrollWidth > window.innerWidth
      ), false, "页面不应横向溢出");
      return {
        points: await page.evaluate(() => {
          const chart = Chart.getChart("fdProfitChart");
          return chart ? chart.data.datasets[0].data.map(point => point.y) : [];
        }),
        history: await page.locator("#fdSnapsBody").textContent(),
        realized: await page.locator("#fdRealizedBody").textContent()
      };
    } finally {
      await page.close();
    }
  }
  try {
    const actual = await check(null, {
      "持仓收益": "−¥2,702.93", "已实现收益": "+¥63.11", "累计收益": "−¥2,639.82"
    });
    assert.ok(Math.abs(actual.points[1] - (-2639.82)) < 0.000001);
    assert.match(actual.realized, /已清仓.*63\.11/);
    assert.match(actual.history, /2,639\.82/);
    await check(null, { "累计收益": "−¥2,639.82" }, { width: 390, height: 844 });
    const before = { holdings: [{ id: "test", invested: 100, value: 110 }] };
    await check({ "2026-10-17": before }, {
      "持仓收益": "+¥10.00", "已实现收益": "+¥0.00", "累计收益": "+¥10.00"
    });
    const closed = await check({
      "2026-10-17": before,
      "2026-11-24": { holdings: [], realized: { test: 10 } }
    }, { "持仓收益": "+¥0.00", "已实现收益": "+¥10.00", "累计收益": "+¥10.00" });
    assert.deepEqual(closed.points, [10, 10], "清仓收益不应从曲线消失");
    await check({
      "2026-11-24": { holdings: [{ id: "test", invested: 50, value: 45 }], realized: { test: -10 } }
    }, { "持仓收益": "−¥5.00", "已实现收益": "−¥10.00", "累计收益": "−¥15.00" });
    console.log("PASS: 真实收益、移动端、旧快照兼容、全部清仓、部分卖出亏损及图表");
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
