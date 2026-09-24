"""Playwright smoke test (Chromium). HOG_UI = path of the built page, HOG_SHOTS = screenshot folder.
Needs network for the live GBIF/Wikidata/GND/OSM lookups."""
import os
from pathlib import Path
URL = Path(os.environ.get("HOG_UI", "HistOrniGraph_Validierung.html")).resolve().as_uri()
SHOTS = os.environ.get("HOG_SHOTS", "shots")
os.makedirs(SHOTS, exist_ok=True)
import asyncio, zipfile
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(viewport={'width':1500,'height':1000}, accept_downloads=True); pg = await ctx.new_page()
        errs=[]; pg.on('pageerror', lambda e: errs.append(str(e))); pg.on('dialog', lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(URL)
        await pg.wait_for_selector('#loading', state='detached', timeout=60000)
        await pg.evaluate("localStorage.clear()"); await pg.reload(); await pg.wait_for_selector('#loading', state='detached', timeout=60000)
        await pg.wait_for_timeout(800); await pg.keyboard.press('Escape'); await pg.fill('#who','Test')
        await pg.click('.task[data-t="qa_flags"]'); await pg.wait_for_timeout(300)
        await pg.fill('#qsearch','L01-e0014'); await pg.wait_for_timeout(600)
        await pg.click('.qi:has-text("Kein Vogel")'); await pg.wait_for_timeout(400)
        await pg.screenshot(path=SHOTS + '/40_qa_corr_form.png')
        await pg.fill('.corrslot .c-new','Birkhenne'); await pg.wait_for_timeout(200)
        await pg.fill('.corrslot .c-sci','Lyrurus tetrix'); await pg.fill('.corrslot .c-note','laut Scan „Birkhenne“')
        await pg.click('.corrslot .c-save'); await pg.wait_for_timeout(500)
        await pg.fill('#qsearch','L01-e0024'); await pg.wait_for_timeout(600)
        await pg.click('.qi:has-text("Kein Ort")'); await pg.wait_for_timeout(400)
        await pg.fill('.corrslot .c-new','Kaufbeuren'); await pg.wait_for_timeout(200)
        await pg.screenshot(path=SHOTS + '/41_qa_place_hint.png')
        await pg.keyboard.press('Enter'); await pg.wait_for_timeout(500)
        await pg.screenshot(path=SHOTS + '/42_qa_place_saved.png')
        # passage-level in taxon merges, scope all
        await pg.click('.task[data-t="taxon_merges"]'); await pg.wait_for_timeout(400)
        await pg.fill('#qsearch','Blauer Gimpel'); await pg.wait_for_timeout(600)
        await pg.click('.psg [data-corr]'); await pg.wait_for_timeout(200)
        await pg.fill('.psg .c-new','Blaumeise'); await pg.click('.psg .c-save'); await pg.wait_for_timeout(500)
        await pg.screenshot(path=SHOTS + '/43_merge_corr.png')
        await pg.click('.task[data-t="__corr"]'); await pg.wait_for_timeout(300); await pg.screenshot(path=SHOTS + '/44_corrlist.png'); await pg.keyboard.press('Escape')
        await pg.click('#btnExport'); await pg.wait_for_timeout(300)
        async with pg.expect_download() as dl: await pg.click('#exZip')
        d = await dl.value; await d.save_as(SHOTS + '/export2.zip')
        z = zipfile.ZipFile(SHOTS + '/export2.zip'); print(z.read('review/value_corrections.csv').decode())
        import csv, io
        q = [r for r in csv.DictReader(io.StringIO(z.read('review/qa_flags.csv').decode())) if r['decision']]; print([(r['entry_id'], r['reason'], r['decision'], r['correction']) for r in q])
        open(SHOTS + '/value_corrections.csv','wb').write(z.read('review/value_corrections.csv'))
        print('errs', errs); await b.close()
asyncio.run(main())
