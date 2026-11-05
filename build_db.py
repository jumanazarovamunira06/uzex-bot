"""Build uzex.db from the UZEX CSV files (typed helper columns + indexes). Usage: python build_db.py [csv_dir] [out.db]"""
import sqlite3, sys, glob, os
import pandas as pd

SRC = sys.argv[1] if len(sys.argv) > 1 else "uzex_spot_data"
OUT = sys.argv[2] if len(sys.argv) > 2 else "uzex.db"

# canonical Russian region name for every Uzbek/Russian spelling (contracts are RU, other files are UZ)
REG = {"Toshkent shahri": "г. Ташкент", "Toshkent viloyati": "Ташкентская область", "Samarqand viloyati": "Самаркандская область",
       "Buxoro viloyati": "Бухарская область", "Namangan viloyati": "Наманганская область", "Farg‘ona viloyati": "Ферганская область",
       "Xorazm viloyati": "Хорезмская область", "Qashqadaryo viloyati": "Кашкадарьинская область", "Navoiy viloyati": "Навоийская область",
       "Sirdaryo viloyati": "Сырдарьинская область", "Andijon viloyati": "Андижанская область", "Surxondaryo viloyati": "Сурхандарьинская область",
       "Jizzax viloyati": "Джизакская область", "Qoraqalpog‘iston Respublikasi": "Республика Каракалпакстан"}

def num(s):  # '1 250 000.50' -> float
    return pd.to_numeric(s.astype("string").str.replace(r"[\s\u00a0]", "", regex=True).str.replace(",", ".", regex=False), errors="coerce")

def iso(s):  # DD.MM.YYYY -> YYYY-MM-DD (sortable)
    return pd.to_datetime(s, format="%d.%m.%Y", errors="coerce").dt.strftime("%Y-%m-%d")

def rd(f): return pd.read_csv(os.path.join(SRC, f), dtype=str, keep_default_na=False, na_values=[""])

if os.path.exists(OUT): os.remove(OUT)
con = sqlite3.connect(OUT)

c = rd("contracts.csv")
c["price_num"] = num(c["Базисная цена"]); c["reg_iso"] = iso(c["Дата регистрации"]); c["valid_iso"] = iso(c["Действует до"])
c["region_ru"] = c["Регион"]
c.to_sql("contracts", con, index=False)

d = pd.concat([rd(os.path.basename(f)) for f in sorted(glob.glob(os.path.join(SRC, "deals_*.csv")))], ignore_index=True)
d["date_iso"] = iso(d["Дата сделки"]); d["year"] = d["date_iso"].str[:4]
for src, dst in [("Сумма сделки", "amount_num"), ("Стартовая цена", "start_price_num"), ("Количество", "qty_num"),
                 ("Лот", "lot_num"), ("Поставлено", "delivered_num")]:
    d[dst] = num(d[src])
d["volume_units"] = d["qty_num"] * d["lot_num"]
d["unit_price"] = d["amount_num"] / d["volume_units"]
d["region_ru"] = d["Регион"].map(REG).fillna(d["Регион"])
d["name_lc"] = d["Наименование товара"].str.lower()          # fast case-insensitive product search
d["currency"] = d["Номер контракта"].map(c.set_index("Номер контракта")["Валюта"])   # deal amounts are in the contract currency
d.to_sql("deals", con, index=False, chunksize=50000)

p = rd("participants.csv"); p["region_ru"] = p["Регион"].map(REG).fillna(p["Регион"]); p.to_sql("participants", con, index=False)
b = rd("brokers.csv"); b["region_ru"] = b["Регион"].map(REG).fillna(b["Регион"]); b.to_sql("brokers", con, index=False)
u = rd("usd_rates.csv"); u["date_iso"] = iso(u["Дата"]); u["rate_num"] = num(u["Курс"]); u.to_sql("usd_rates", con, index=False)

for sql in ['CREATE INDEX i_d_contract ON deals("Номер контракта")', 'CREATE INDEX i_d_date ON deals(date_iso)',
            'CREATE INDEX i_d_seller ON deals("ИНН продавца")', 'CREATE INDEX i_d_buyer ON deals("ИНН покупателя")',
            'CREATE INDEX i_d_region ON deals(region_ru)', 'CREATE INDEX i_d_state ON deals("Состояние сделки")',
            'CREATE INDEX i_d_bs ON deals("Брокер продавца")', 'CREATE INDEX i_d_bb ON deals("Брокер покупателя")',
            'CREATE INDEX i_d_no ON deals("Номер сделки")',
            'CREATE INDEX i_c_no ON contracts("Номер контракта")', 'CREATE INDEX i_c_region ON contracts(region_ru)',
            'CREATE INDEX i_c_inn ON contracts("ИНН продавца")', 'CREATE INDEX i_p_inn ON participants("ИНН")',
            'CREATE INDEX i_b_code ON brokers("Код брокера")', 'CREATE INDEX i_u_date ON usd_rates(date_iso)']:
    con.execute(sql)
con.commit()
for t in ["contracts", "deals", "participants", "brokers", "usd_rates"]:
    print(t, con.execute(f"select count(*) from {t}").fetchone()[0])
print("deals without amount:", con.execute("select count(*) from deals where amount_num is null").fetchone()[0],
      "| unmapped regions:", con.execute("select count(distinct region_ru) from deals").fetchone()[0])
con.execute("VACUUM"); con.close()
print("size MB:", round(os.path.getsize(OUT) / 1e6, 1))