<h1 align="center">🔌 Proxy-Scraper</h1>

<p align="center">
  <strong>Ultimate proxy scraper & checker</strong><br>
  Deep-search across <strong>90+ public sources</strong> — HTTP, HTTPS, SOCKS4, SOCKS5.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%2B-blue?style=flat-square" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/sources-90%2B-orange?style=flat-square" alt="90+ Sources">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
</p>

---

## ✨ Features

- **90+ Sources** — GitHub raw lists, CDNs, JSON APIs, HTML table parsers, and deep paginated APIs.
- **Deep Search** — GeoNode API scraped across 20 pages per protocol (up to 10,000 proxies per type).
- **Multi-Protocol** — HTTP, HTTPS, SOCKS4, SOCKS5 with automatic type tagging.
- **Concurrent Checking** — Validate thousands of proxies with configurable thread pools.
- **Clean CLI** — `scrape`, `check`, and `--list-sources` subcommands.
- **Smart Deduplication** — Eliminates duplicates automatically across all 90+ sources.
- **Structured Output** — Save per proxy type or into a single file.
- **Resilient** — Retries, timeouts, and graceful handling of dead sources.

---

## 📦 Installation

```bash
git clone https://github.com/faizgans14/Proxy-Scrape.git
cd Proxy-Scrape

# (Optional) virtual environment
python3 -m venv venv
source venv/bin/activate  # macOS / Linux
# venv\Scripts\activate   # Windows

pip install requests
```

---

## 🚀 Usage

### Scrape

```bash
# Deep-search from ALL 90+ sources
python scrape.py scrape --all

# Scrape specific sources only
python scrape.py scrape --source github-gfpcom-http deep-geonode-http web-free-proxy-list

# Split output by type: proxies.http.txt, proxies.socks5.txt, etc.
python scrape.py scrape --all --by-type

# Custom output / timeout / workers
python scrape.py scrape --all -o my_proxies.txt --timeout 60 --workers 30
```

### Check

```bash
python scrape.py check --file proxies.txt
python scrape.py check --file proxies.txt --workers 200 --timeout 15
python scrape.py check --file proxies.txt --output live.txt dead.txt
```

### List Sources

```bash
python scrape.py scrape --list-sources
```

---

## 📁 Structure

```
Proxy-Scrape/
├── scrape.py          # Main script (90+ sources, scraper, checker, CLI)
├── proxies.txt        # Default output
├── live_proxies.txt   # Working proxies
├── dead_proxies.txt   # Dead proxies
└── README.md
```

---

## 🔗 Built-in Sources (90+)

### GitHub Raw Lists (60+)

| Source | Protocols |
|--------|-----------|
| `github-thespeedx-http/socks4/socks5` | HTTP / SOCKS4 / SOCKS5 |
| `github-clarketm` | Mixed |
| `github-jetkai` | Mixed |
| `github-monosans-http/socks4/socks5` | HTTP / SOCKS4 / SOCKS5 |
| `github-proxylist-http/socks4/socks5` | HTTP / SOCKS4 / SOCKS5 |
| `github-iplocate-http/https/socks4/socks5` | HTTP / HTTPS / SOCKS4 / SOCKS5 |
| `github-proxifly-http/https/socks4/socks5` | HTTP / HTTPS / SOCKS4 / SOCKS5 |
| `github-gfpcom-http/https/socks4/socks5` | HTTP / HTTPS / SOCKS4 / SOCKS5 *(500K+ each)* |
| `github-vpslab-http/ssl/nossl/elite/anonymous/transparent` | HTTP variants |
| `github-vpslab-socks4/socks5/all` | SOCKS4 / SOCKS5 / Mixed |
| `github-vpslab-all-elite/anonymous/transparent` | Mixed variants |
| `github-thordata-http/https/socks4/socks5/all` | Daily verified |
| `github-sevenworks-http/socks4/socks5` | HTTP / SOCKS4 / SOCKS5 |
| `github-murongpig-http/socks4/socks5` | HTTP / SOCKS4 / SOCKS5 |
| `github-prxchk-http/socks4/socks5` | HTTP / SOCKS4 / SOCKS5 |
| `github-zevtyardt-http/socks4/socks5` | HTTP / SOCKS4 / SOCKS5 |
| `github-rdavydov-http/socks4/socks5` | HTTP / SOCKS4 / SOCKS5 |
| `github-proxy4parsing` | HTTP |
| `github-hookzof-socks5` | SOCKS5 |
| `github-shiftytr-http/socks4/socks5` | HTTP / SOCKS4 / SOCKS5 |
| `github-zloi-hideip` | HTTP |
| `github-sunny9577` | Mixed |
| `github-mmpx12` | Mixed |
| `github-anonym0us-http/socks4/socks5` | HTTP / SOCKS4 / SOCKS5 |
| `github-roosterkid` | HTTPS |

### CDN Mirrors (4)

| Source | Protocols |
|--------|-----------|
| `cdn-proxifly-http/socks4/socks5/all` | HTTP / SOCKS4 / SOCKS5 / Mixed *(jsDelivr CDN)* |

### APIs (8)

| Source | Protocols |
|--------|-----------|
| `api-proxylist-http/https/socks4/socks5` | HTTP / HTTPS / SOCKS4 / SOCKS5 |
| `api-proxyscrape-http/socks4/socks5` | HTTP / SOCKS4 / SOCKS5 |
| `api-pubproxy` | Mixed |

### Deep / Paginated JSON APIs (4)

| Source | Protocols | Depth |
|--------|-----------|-------|
| `deep-geonode-http/https/socks4/socks5` | HTTP / HTTPS / SOCKS4 / SOCKS5 | 20 pages × 500 = **10,000** per type |

### Web — HTML Table Parsers (6)

| Source | Protocols |
|--------|-----------|
| `web-free-proxy-list` | HTTP |
| `web-sslproxies` | HTTPS |
| `web-us-proxy` | HTTP |
| `web-socks-proxy` | SOCKS5 |
| `web-uk-proxy` | HTTP |
| `web-anonymous-proxy` | HTTP |

### Other

| Source | Protocols |
|--------|-----------|
| `other-spysme` | Mixed |

---

## ⚙️ Configuration

Edit constants in `scrape.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `DEFAULT_TIMEOUT` | `30` | Scrape request timeout |
| `CHECK_TIMEOUT` | `10` | Proxy check timeout |
| `MAX_WORKERS` | `100` | Max checker threads |

---

## 📝 Example Output

```
[14:32:10] INFO: Deep-search scraping from 90 source(s)...
[14:32:11] INFO: [github-gfpcom-http] OK | +511,769 new | total 511,769 | 4.20s
[14:32:12] INFO: [deep-geonode-http] OK | +10,000 new | total 521,769 | 8.50s
[14:32:15] INFO: [web-free-proxy-list] OK | +300 new | total 522,069 | 0.30s
...
[14:35:45] INFO: Scraping finished. Total unique proxies: 2,145,203

====================================================
 PROXY SCRAPE SUMMARY
====================================================
  HTTP      :  1,020,000
  HTTPS     :    480,000
  SOCKS4    :    320,000
  SOCKS5    :    325,203
----------------------------------------------------
  TOTAL     :  2,145,203
====================================================
```

---

## ⚠️ Disclaimer

Proxies are scraped from **public sources**. No guarantee of speed, security, or uptime. Use at your own risk and in accordance with local laws.

---

## 📄 License

MIT License — see repository for details.

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/faizdotid">faizdotid</a> with <a href="https://kimi.moonshot.cn">Kimi</a> 🤖
</p>
