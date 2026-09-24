"""Playwright smoke test (Chromium). HOG_UI = path of the built page, HOG_SHOTS = screenshot folder.
Needs network for the live GBIF/Wikidata/GND/OSM lookups."""
import os
from pathlib import Path
URL = Path(os.environ.get("HOG_UI", "HistOrniGraph_Validierung.html")).resolve().as_uri()
SHOTS = os.environ.get("HOG_SHOTS", "shots")
os.makedirs(SHOTS, exist_ok=True)
import asyncio, zipfile, csv, io
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(); ctx = await b.new_context(viewport={'width':1500,'height':1000}, accept_downloads=True); pg = await ctx.new_page()
        errs=[]; pg.on('pageerror', lambda e: errs.append(str(e))); pg.on('dialog', lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(URL)
        await pg.wait_for_selector('#loading', state='detached', timeout=60000)
        await pg.evaluate("localStorage.clear()"); await pg.reload(); await pg.wait_for_selector('#loading', state='detached', timeout=60000)
        await pg.wait_for_timeout(800); await pg.keyboard.press('Escape'); await pg.fill('#who','Test')
        await pg.screenshot(path=SHOTS + '/50_overview.png')
        # 1 GBIF German name in merges
        await pg.click('.task[data-t="taxon_merges"]'); await pg.wait_for_timeout(2500)
        print('gbif de:', await pg.inner_text('.facts'))
        await pg.screenshot(path=SHOTS + '/51_merge.png')
        # passage correction (entry only)
        await pg.click('.psg [data-corr]'); await pg.wait_for_timeout(200)
        print('radios in form:', await pg.locator('.corrform input[type=radio]').count())
        await pg.fill('.psg .c-new','Staar'); await pg.click('.psg .c-save'); await pg.wait_for_timeout(400)
        # 2 persons: pick Wikidata candidate -> GND auto from P227
        await pg.click('.task[data-t="person_links"]'); await pg.wait_for_timeout(400)
        await pg.fill('#qsearch','Walter Wüst'); await pg.wait_for_timeout(600)
        await pg.click('.cand[data-qid]'); await pg.wait_for_timeout(3000)
        print('person gnd block:', (await pg.inner_text('.card .cb')).replace('\n',' | ')[:400])
        await pg.screenshot(path=SHOTS + '/52_person.png')
        # GND search for a person without candidates
        await pg.fill('#qsearch','Laubmann'); await pg.wait_for_timeout(600)
        await pg.click('#gndbtn'); await pg.wait_for_timeout(3000)
        print('gnd results:', (await pg.inner_text('#wres'))[:300].replace('\n',' | '))
        r = pg.locator('#wres .r[data-k]')
        if await r.count(): await r.first.click(); await pg.wait_for_timeout(500)
        await pg.screenshot(path=SHOTS + '/53_gnd.png')
        # 3 places: Wikidata search -> coords + geonames
        await pg.click('.task[data-t="place_links"]'); await pg.wait_for_timeout(500)
        await pg.fill('#qsearch','Ismaninger Teichgebiet'); await pg.wait_for_timeout(600)
        await pg.fill('#nq','Ismaning'); await pg.click('#pwbtn'); await pg.wait_for_timeout(3000)
        await pg.click('#nres .r[data-k]'); await pg.wait_for_timeout(3000)
        print('place fix:', await pg.inner_text('.fixed'))
        await pg.screenshot(path=SHOTS + '/54_place.png')
        await pg.click('#btnExport'); await pg.wait_for_timeout(300)
        async with pg.expect_download() as dl: await pg.click('#exZip')
        d = await dl.value; await d.save_as(SHOTS + '/export3.zip')
        z = zipfile.ZipFile(SHOTS + '/export3.zip')
        pr = list(csv.DictReader(io.StringIO(z.read('review/person_link_review.csv').decode())))
        print('person header has gnd:', 'gnd' in pr[0], [ (r['person_name'], r['qid'], r['gnd'], r['decision']) for r in pr if r['decision']=='y'])
        pl = [r for r in csv.DictReader(io.StringIO(z.read('review/place_link_review.csv').decode())) if r['decision']]
        print('place rows:', [(r['place_name'], r['lat'], r['lon'], r['geonames_id'], r['qid'], r['source']) for r in pl])
        print(z.read('review/value_corrections.csv').decode())
        open(SHOTS + '/person_link_review.csv','wb').write(z.read('review/person_link_review.csv'))
        open(SHOTS + '/place_link_review.csv','wb').write(z.read('review/place_link_review.csv'))
        print('errs', errs); await b.close()
asyncio.run(main())
