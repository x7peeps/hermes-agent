---
name: email-osint-trace
description: |
  Open-source email intelligence (OSINT) — systematic email address tracing
  across search engines, social platforms, breach databases, and public
  registries. Covers Chinese and global platforms with proxy-aware networking.
version: 1.0.0
author: pwndazhang
license: MIT
metadata:
  hermes:
    tags: [osint, email, trace, security, reconnaissance, enumeration]
    category: security
    related_skills: [domain-osint-trace, malware-sample-analysis]
---

# Email OSINT Trace

Systematic email address tracing using open-source intelligence (OSINT)
techniques. Traces an email across search engines, social platforms, breach
databases, paste sites, and public registries to build a digital footprint.

## When to Use

- User provides an email address for tracing/investigation
- Security incident response needs email attribution
- Threat intelligence requires actor email enrichment
- Due diligence on a person/organization via email

## The Iron Rule

**Never ask the user to manually copy cookies, bypass CAPTCHAs, or run
commands.** All reconnaissance must be autonomous. Use proxy rotation and
browser automation to overcome anti-bot measures.

## Prerequisites

- Python 3.9+ with `requests` library
- Working HTTP proxy (check common ports: 7890, 1086, 1087, 8090)
- `urllib` (stdlib) as fallback

## The Trace Pipeline

### Phase 1: Infrastructure Setup

```python
# Detect working proxy
for port in [7890, 1086, 1087, 8090]:
    try:
        r = requests.get('https://httpbin.org/ip',
            proxies={'https': f'http://127.0.0.1:{port}'}, timeout=10)
        PROXY = port
        break
    except:
        pass

proxies = {'http': f'http://127.0.0.1:{PROXY}', 'https': f'http://127.0.0.1:{PROXY}'}
headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
```

### Phase 2: Search Engine Recon

Search in this order (most reliable first):

1. **Bing** — `https://www.bing.com/search?q="{email}"`
2. **DuckDuckGo HTML** — `https://html.duckduckgo.com/html/?q="{email}"`
3. **Baidu** — `https://www.baidu.com/s?wd="{email}"` (for Chinese targets)

Parse results with regex:
```python
results = re.findall(r'<li[^>]*class="b_algo"[^>]*>(.*?)</li>', r.text, re.DOTALL)
```

Search variations:
- Exact email: `"{email}"`
- Username only: `"{local_part}"`
- Site-specific: `site:github.com "{username}"`
- Forum/paste: `"{email}" forum`, `"{email}" site:pastebin.com`

### Phase 3: Social Platform Enumeration

Check these platforms via direct URL or API:

| Platform | URL Pattern | Detection Method |
|----------|-------------|-----------------|
| GitHub | `https://api.github.com/users/{user}` | JSON 404 vs 200 |
| GitLab | `https://gitlab.com/api/v4/users?username={user}` | Empty array = not found |
| Docker Hub | `https://hub.docker.com/v2/users/{user}/` | `{"detail":"not_found"}` |
| Telegram | `https://t.me/{user}` | Page title + content |
| Instagram | `https://www.instagram.com/{user}/` | Extract JSON from page |
| Reddit | `https://www.reddit.com/user/{user}/` | 403 = rate limit, 404 = not found |
| Steam | `https://steamcommunity.com/id/{user}` | Title contains "Error" |
| Gravatar | `https://en.gravatar.com/{md5_hash}.json` | 404 = not found |
| WordPress | `https://{user}.wordpress.com` | Redirect to /typo/ = not found |
| Slideshare | `https://www.slideshare.net/{user}` | May have Cloudflare |

**IMPORTANT**: Status 200 ≠ account exists. Many platforms return 200 with
login redirects for non-existent users. Always check page content:
- Look for "not found", "page doesn't exist" in body
- Extract profile JSON/data from page
- Check if username appears in content

### Phase 4: Breach Database Check

```python
# breachdirectory.org (free API)
r = requests.get('https://api.breachdirectory.org/',
    params={'func': 'email', 'email': target_email}, proxies=proxies, timeout=20)

# HaveIBeenPwned (needs API key)
r = requests.get(f'https://haveibeenpwned.com/api/v3/breachedaccount/{email}',
    headers={'hibp-api-key': API_KEY}, proxies=proxies, timeout=20)
```

### Phase 5: Chinese Platform Search

For Chinese targets, also check:
- Weibo: `site:weibo.com "{username}"`
- 知乎: `site:zhihu.com "{username}"`
- 豆瓣: `site:douban.com "{username}"`
- Bilibili: `site:bilibili.com "{username}"`
- CSDN: `site:csdn.net "{username}"`
- 掘金: `site:juejin.cn "{username}"`
- 贴吧: `site:tieba.baidu.com "{username}"`

### Phase 6: Deep Analysis

For confirmed platforms:
1. Extract profile data (name, bio, location, avatar)
2. Find all emails mentioned on profile pages
3. Extract profile photos for reverse image search
4. Check for external links/associated accounts
5. Analyze username structure (pinyin, patterns, language)

## Telegram Profile Extraction

Telegram t.me pages contain rich metadata:

```python
# Extract profile name
name = re.search(r'<div[^>]*class="tgme_page_title".*?<span>(.*?)</span>', text, re.DOTALL)

# Extract bio/description
bio = re.search(r'<div[^>]*class="tgme_page_description">(.*?)</div>', text, re.DOTALL)

# Extract profile photo
photo = re.search(r'<img[^>]*class="tgme_page_photo_image"[^>]*src="([^"]+)"', text)

# Check OG metadata
og_desc = re.findall(r'<meta[^>]*property="og:description"[^>]*content="([^"]+)"', text)
```

## Report Structure

Every trace report must include:

1. **Summary table** — email, username, threat level
2. **Confirmed platforms** — with profile data
3. **Excluded platforms** — with detection method
4. **Username analysis** — structure, language, possible meanings
5. **Breach status** — known leaks or clean
6. **Web traces** — forums, code, paste sites
7. **Conclusion** — user profile sketch, risk assessment

## Pitfalls

- **Google blocks automated requests** — use Bing as primary, Google via browser
- **Status 200 ≠ exists** — always verify page content
- **Instagram returns 200 for login redirect** — check for profile JSON in page
- **Slideshare has Cloudflare** — may need browser automation
- **Some platforms rate-limit** — add delays between requests
- **Chinese platforms may need Chinese IP** — use proxy with appropriate geo
- **Never claim "not found" without checking content** — a 200 with error page is not a success

## Verification

After completing a trace:
1. Every "confirmed" platform has verifiable evidence (URL, data, screenshot)
2. Every "not found" platform was checked via at least one method
3. Report includes search queries used (for reproducibility)
4. All attempts and failures are logged
