"""Playwright smoke test (Chromium). HOG_UI = path of the built page, HOG_SHOTS = screenshot folder.
Needs network for the live GBIF/Wikidata/GND/OSM lookups."""
import os
from pathlib import Path
URL = Path(os.environ.get("HOG_UI", "HistOrniGraph_Validierung.html")).resolve().as_uri()
SHOTS = os.environ.get("HOG_SHOTS", "shots")
os.makedirs(SHOTS, exist_ok=True)
import asyncio, zipfile, io, csv, os
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(viewport={'width': 1500, 'height': 950}, accept_downloads=True)
        pg = await ctx.new_page()
        errs = []
        pg.on('console', lambda m: m.type == 'error' and errs.append(m.text))
        pg.on('pageerror', lambda e: errs.append('PAGEERROR ' + str(e)))
        await pg.goto(URL)
        await pg.wait_for_selector('#loading', state='detached', timeout=60000)
        await pg.wait_for_timeout(600)
        await pg.screenshot(path=SHOTS + '/0_help.png')
        await pg.keyboard.press('Escape')
        await pg.fill('#who', 'Test')
        await pg.screenshot(path=SHOTS + '/1_overview.png')
        for i, tid in enumerate(['taxon_merges','person_merges','place_merges','habitat_merges','taxon_links','person_links','place_links','habitat_links','qa_flags']):
            await pg.click(f'.task[data-t="{tid}"]')
            await pg.wait_for_timeout(700)
            await pg.screenshot(path=fSHOTS + '/{i+2}_{tid}.png')
            await pg.keyboard.press('y' if i % 2 == 0 else 'n')
            await pg.wait_for_timeout(300)
            await pg.keyboard.press('u')
            await pg.wait_for_timeout(300)
        # person link: pick candidate 2
        await pg.click('.task[data-t="person_links"]'); await pg.wait_for_timeout(400)
        await pg.keyboard.press('2'); await pg.wait_for_timeout(300)
        # place link: set manual coordinate
        await pg.click('.task[data-t="place_links"]'); await pg.wait_for_timeout(600)
        await pg.fill('#ll', '48.2, 11.7'); await pg.click('#llbtn'); await pg.wait_for_timeout(400)
        await pg.keyboard.press('k'); await pg.wait_for_timeout(500)
        await pg.screenshot(path=SHOTS + '/20_place_fix.png')
        # habitat fix
        await pg.click('.task[data-t="habitat_links"]'); await pg.wait_for_timeout(400)
        await pg.fill('#eq', 'reed'); await pg.wait_for_timeout(300)
        await pg.click('#eres .r[data-c]'); await pg.wait_for_timeout(400)
        # scan
        await pg.click('.task[data-t="taxon_merges"]'); await pg.wait_for_timeout(400)
        btn = await pg.query_selector('[data-scan]')
        print('scan button', bool(btn))
        # merge manual
        await pg.fill('#manV', 'Foo'); await pg.fill('#manC', 'Bar'); await pg.click('#manAdd'); await pg.wait_for_timeout(300)
        # full entry toggle
        m = await pg.query_selector('button.more')
        if m: await m.click(); await pg.wait_for_timeout(200)
        await pg.click('#btnExport'); await pg.wait_for_timeout(300)
        async with pg.expect_download() as dl:
            await pg.click('#exZip')
        d = await dl.value; path = SHOTS + '/export.zip'; await d.save_as(path)
        z = zipfile.ZipFile(path); print(z.namelist())
        for n in z.namelist():
            if n.endswith('.csv'):
                rows = list(csv.DictReader(io.StringIO(z.read(n).decode())))
                decs = {}
                for r in rows: decs[r.get('decision','')] = decs.get(r.get('decision',''), 0) + 1
                print(n, len(rows), decs)
        print(z.read('validation_log.csv').decode()[:1500])
        # reload persistence
        await pg.reload(); await pg.wait_for_selector('#loading', state='detached', timeout=60000)
        print('after reload task title', await pg.text_content('#qtitle'))
        print('ERRORS', errs)
        await b.close()
asyncio.run(main())
