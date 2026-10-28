# Grafiky litovle.cz

Lokální deterministický generátor čtvercových PNG 1080 × 1080 px. Vykresluje dva layouty: změnu svozu (`waste_change`) a přehled jednání (`council_summary`). Neobsahuje AI ani síťové volání při generování.

## Instalace a spuštění

Z adresáře `social_graphics`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python main.py examples/waste_change.yaml waste.png
.venv/bin/python main.py examples/council_summary.yaml rada.png
.venv/bin/python main.py examples/council_summary_three.json zastupitelstvo.png
```

Program při dlouhém textu vypíše konkrétní pole a ukončí se s kódem 2. Výstup nevytváří, pokud kontrola layoutu selže.

Ukázka `council_summary_from_resolutions.yaml` používá `resolution_id`; vyžaduje roční JSON export v `../export/assets/usneseni/data/` nebo předání jeho umístění přes `--resolutions-dir`. Tento adresář je v repozitáři ignorovaný Gitem a po čistém klonování není dostupný.

Hotové ukázky jsou v [`previews/waste_change.png`](previews/waste_change.png) a [`previews/council_summary.png`](previews/council_summary.png). Testy spustíte příkazem `PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v`.

## Vstup

Vzorové soubory v `examples/` ukazují všechna povinná pole. Lze použít YAML (`.yaml`, `.yml`) nebo JSON (`.json`). `waste_change` podporuje volitelné `accent_lines`, seznam čísel řádků od 1, které budou modré. Výchozí je poslední řádek. U `council_summary` lze uvést `branding.top_label` nebo `null`; počet bodů musí být 3 nebo 4. Dostupné ikony jsou vypsané v `generator/icons.py`.

Ikonu lze určit ručně polem `icon`. Pokud chybí, musí mít bod `resolution_id`, například `RM/2568/81/2026`. Generátor toto ID vyhledá v `../export/assets/usneseni/data/2026.json`, vezme `classification.category` a podle pevné [mapy 14 kategorií](generator/icon_selection.py) vybere výchozí ikonu. Jiný adresář exportu lze předat přepínačem `--resolutions-dir`. Zadané `resolution_id` se ověřuje i při ruční ikoně. Pokud má modelové skóre klasifikace méně než 0,70, automatický výběr skončí s chybou a vyžádá ruční `icon`; skóre není kalibrovaná pravděpodobnost, ale nízká hodnota signalizuje potřebu kontroly. Ruční `icon` má přednost: klasifikace někdy vystihuje širší oblast, ale pro grafiku se hodí konkrétnější symbol, například `water` místo obecné `construction` pro kanalizaci. Nadpis ani popis generátor neanalyzuje a při generování nespouští žádný klasifikátor. Dostupné názvy a SVG soubory jsou v `generator/icons.py`; neznámý název vyvolá chybu.

Logo je vždy načteno z `assets/litovle_logo.png`. Jde o věrný raster oficiálního [loga litovle.cz](https://litovle.cz/assets/img/logo_cele.svg), převedený ze zdrojového SVG bez překreslování. Při převodu byla rozšířena plocha SVG doprava, aby se neořízlo poslední „A“ v podtitulu „INICIATIVA“. Soubor PNG musí zůstat na uvedené cestě. Ikony jsou lokální SVG soubory z [Lucide](https://github.com/lucide-icons/lucide) pod licencí ISC; její text je v `assets/icons/LICENSE`. Font [Inter](https://github.com/google/fonts/tree/main/ofl/inter) je pod OFL, viz `assets/fonts/OFL.txt`.
