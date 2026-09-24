"""Playwright smoke test (Chromium). HOG_UI = path of the built page, HOG_SHOTS = screenshot folder.
Needs network for the live GBIF/Wikidata/GND/OSM lookups."""
import os
from pathlib import Path
URL = Path(os.environ.get("HOG_UI", "HistOrniGraph_Validierung.html")).resolve().as_uri()
SHOTS = os.environ.get("HOG_SHOTS", "shots")
os.makedirs(SHOTS, exist_ok=True)
import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(); pg = await b.new_page(viewport={'width':1500,'height':950})
        errs=[]; pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto(URL)
        await pg.wait_for_selector('#loading', state='detached', timeout=60000)
        await pg.evaluate("localStorage.clear()"); await pg.reload(); await pg.wait_for_selector('#loading', state='detached', timeout=60000)
        await pg.wait_for_timeout(800); await pg.keyboard.press('Escape')
        await pg.click('.task[data-t="taxon_links"]'); await pg.wait_for_timeout(400)
        await pg.fill('#gq','Hirundo rustica'); await pg.click('#gbtn'); await pg.wait_for_timeout(4000)
        print('gbif', (await pg.inner_text('#gres'))[:200].replace('\n',' | '))
        await pg.screenshot(path=SHOTS + '/30_taxonlink.png')
        await pg.click('.task[data-t="person_links"]'); await pg.wait_for_timeout(400)
        await pg.click('#wbtn'); await pg.wait_for_timeout(4000)
        print('wd', (await pg.inner_text('#wres'))[:200].replace('\n',' | '))
        await pg.click('.task[data-t="place_links"]'); await pg.wait_for_timeout(400)
        await pg.fill('#nq','Ismaninger Teichgebiet'); await pg.click('#nbtn'); await pg.wait_for_timeout(4000)
        print('osm', (await pg.inner_text('#nres'))[:200].replace('\n',' | '))
        print('errs', errs); await b.close()
asyncio.run(main())
