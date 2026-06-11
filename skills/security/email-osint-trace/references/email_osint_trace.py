#!/usr/bin/env python3
"""
Email OSINT Trace Script — reference implementation for the email-osint-trace skill.

Usage:
    python email_osint_trace.py <email>
    python email_osint_trace.py lianjiecongyesse@outlook.com

Outputs: Structured trace report to stdout and saves markdown report to archive.
"""

import requests
import re
import json
import hashlib
import sys
from datetime import datetime

# ── Phase 1: Infrastructure ──────────────────────────────────────────

def detect_proxy():
    """Find a working local proxy port."""
    for port in [7890, 1086, 1087, 8090]:
        try:
            r = requests.get('https://httpbin.org/ip',
                proxies={'https': f'http://127.0.0.1:{port}'}, timeout=10)
            return port
        except:
            pass
    return None

def setup(email):
    proxy_port = detect_proxy()
    proxies = {'http': f'http://127.0.0.1:{proxy_port}', 'https': f'http://127.0.0.1:{proxy_port}'} if proxy_port else {}
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    local_part = email.split('@')[0]
    return proxies, headers, local_part

# ── Phase 2: Search Engines ─────────────────────────────────────────

def search_bing(email, proxies, headers):
    """Search Bing for exact email and username."""
    results = []
    queries = [f'"{email}"', email.split('@')[0], f'{email} forum', f'{email} data breach']
    for q in queries:
        try:
            r = requests.get('https://www.bing.com/search', params={'q': q},
                headers=headers, proxies=proxies, timeout=15)
            blocks = re.findall(r'<li[^>]*class="b_algo"[^>]*>(.*?)</li>', r.text, re.DOTALL)
            for block in blocks[:3]:
                url_m = re.search(r'<a[^>]*href="([^"]+)"', block)
                title_m = re.search(r'<h2[^>]*>(.*?)</h2>', block, re.DOTALL)
                snippet_m = re.search(r'<p>(.*?)</p>', block, re.DOTALL)
                if url_m:
                    results.append({
                        'query': q,
                        'title': re.sub(r'<[^>]*>', '', title_m.group(1)) if title_m else '',
                        'url': url_m.group(1),
                        'snippet': re.sub(r'<[^>]*>', '', snippet_m.group(1))[:200] if snippet_m else ''
                    })
        except Exception as e:
            results.append({'query': q, 'error': str(e)})
    return results

def search_baidu(email, proxies, headers):
    """Search Baidu for Chinese-language traces."""
    results = []
    try:
        r = requests.get('https://www.baidu.com/s', params={'wd': f'"{email}"'},
            headers=headers, proxies=proxies, timeout=15)
        links = re.findall(r'<a[^>]*href="(https?://[^"]+)"[^>]*data-tools=', r.text)
        for l in links[:10]:
            results.append({'url': l})
    except Exception as e:
        results.append({'error': str(e)})
    return results

# ── Phase 3: Social Platforms ───────────────────────────────────────

def check_platform(name, url, proxies, headers, detection='status'):
    """Check if a user exists on a platform."""
    try:
        h = headers.copy()
        if 'api.github' in url:
            h['Accept'] = 'application/vnd.github.v3+json'
        r = requests.get(url, headers=h, proxies=proxies, timeout=10, allow_redirects=True)
        
        if detection == 'github_api':
            data = r.json()
            return 'found' if 'message' not in data else 'not_found'
        elif detection == 'gitlab_api':
            data = r.json()
            return 'found' if data else 'not_found'
        elif detection == 'docker_api':
            data = r.json()
            return 'not_found' if data.get('detail') == 'not_found' else 'found'
        elif detection == 'telegram':
            text = r.text.lower()
            target = url.split('/')[-1]
            return 'found' if target in r.text and 'not found' not in text else 'not_found'
        elif detection == 'gravatar':
            return 'found' if r.status_code == 200 else 'not_found'
        else:
            # Default: check for not-found patterns
            text = r.text.lower()
            not_found_patterns = ['page not found', 'not found', 'user not found', 
                                  'does not exist', 'no longer available']
            if r.status_code == 200 and not any(p in text for p in not_found_patterns):
                return 'found'
            elif r.status_code == 404:
                return 'not_found'
            else:
                return f'status_{r.status_code}'
    except Exception as e:
        return f'error: {e}'

def check_telegram_profile(username, proxies, headers):
    """Deep check Telegram profile for data."""
    url = f'https://t.me/{username}'
    try:
        r = requests.get(url, headers=headers, proxies=proxies, timeout=15)
        text = r.text
        result: dict = {}
        
        target = url.split('/')[-1]
        if target not in text:
            result['exists'] = False
            return result
        result['exists'] = True
        
        # Extract profile data
        title = re.findall(r'<title>(.*?)</title>', text)
        if title:
            result['title'] = title[0]
        
        name_match = re.search(r'<div[^>]*class="tgme_page_title"[^>]*>.*?<span[^>]*>(.*?)</span>', text, re.DOTALL)
        if name_match:
            result['name'] = re.sub(r'<[^>]*>', '', name_match.group(1))
        
        desc_match = re.search(r'<div[^>]*class="tgme_page_description"[^>]*>(.*?)</div>', text, re.DOTALL)
        if desc_match:
            result['bio'] = re.sub(r'<[^>]*>', '', desc_match.group(1))
        
        photo_match = re.search(r'<img[^>]*class="tgme_page_photo_image"[^>]*src="([^"]+)"', text)
        if photo_match:
            result['photo'] = photo_match.group(1)
        
        og_desc = re.findall(r'<meta[^>]*property="og:description"[^>]*content="([^"]+)"', text)
        if og_desc:
            result['og_description'] = og_desc[0]
        
        return result
    except Exception as e:
        return {'error': str(e)}

# ── Phase 4: Breach Check ──────────────────────────────────────────

def check_breaches(email, proxies, headers):
    """Check breach databases."""
    results = {}
    
    # breachdirectory.org
    try:
        r = requests.get('https://api.breachdirectory.org/',
            params={'func': 'email', 'email': email},
            proxies=proxies, timeout=20)
        results['breachdirectory'] = r.json() if r.status_code == 200 else f'status_{r.status_code}'
    except Exception as e:
        results['breachdirectory'] = str(e)
    
    return results

# ── Phase 5: Gravatar ──────────────────────────────────────────────

def check_gravatar(email, proxies, headers):
    """Check for Gravatar profile."""
    email_hash = hashlib.md5(email.lower().strip().encode()).hexdigest()
    try:
        r = requests.get(f'https://en.gravatar.com/{email_hash}.json',
            headers=headers, proxies=proxies, timeout=10)
        if r.status_code == 200:
            data = r.json()
            entry = data.get('entry', [{}])[0]
            return {
                'exists': True,
                'display_name': entry.get('displayName'),
                'about': entry.get('aboutMe'),
                'location': entry.get('location'),
                'profile_url': entry.get('profileUrl'),
            }
        return {'exists': False}
    except Exception as e:
        return {'error': str(e)}

# ── Phase 6: Username Analysis ─────────────────────────────────────

def analyze_username(username):
    """Analyze username structure and possible meanings."""
    analysis = {
        'username': username,
        'length': len(username),
        'has_numbers': bool(re.search(r'\d', username)),
        'has_special': bool(re.search(r'[^a-zA-Z0-9]', username)),
    }
    
    # Try common splits
    for sep in ['_', '-', '.', 'cong', 'yesse']:
        if sep in username:
            analysis[f'split_by_{sep}'] = username.split(sep)
    
    return analysis

# ── Main Pipeline ───────────────────────────────────────────────────

def run_trace(email):
    """Run full OSINT trace on an email address."""
    print(f"🔍 Starting email OSINT trace: {email}")
    print(f"⏰ Timestamp: {datetime.now().isoformat()}")
    
    proxies, headers, username = setup(email)
    print(f"📡 Proxy: {'detected' if proxies else 'none'}")
    
    # Phase 3: Social platforms
    print("\n📱 Checking social platforms...")
    platforms = {
        'GitHub': (f'https://api.github.com/users/{username}', 'github_api'),
        'GitLab': (f'https://gitlab.com/api/v4/users?username={username}', 'gitlab_api'),
        'Docker Hub': (f'https://hub.docker.com/v2/users/{username}/', 'docker_api'),
        'Telegram': (f'https://t.me/{username}', 'telegram'),
        'Gravatar': (f'https://en.gravatar.com/{hashlib.md5(email.lower().strip().encode()).hexdigest()}.json', 'gravatar'),
    }
    
    results = {}
    for name, (url, detection) in platforms.items():
        status = check_platform(name, url, proxies, headers, detection)
        results[name] = status
        icon = '✅' if status == 'found' else '❌' if status == 'not_found' else '⚠️'
        print(f"  {icon} {name}: {status}")
    
    # Deep Telegram check if found
    if results.get('Telegram') == 'found':
        print("\n🔍 Deep Telegram analysis...")
        tg_profile = check_telegram_profile(username, proxies, headers)
        results['Telegram_profile'] = tg_profile
        print(f"  Profile: {json.dumps(tg_profile, ensure_ascii=False, indent=2)}")
    
    # Phase 4: Breach check
    print("\n🔓 Checking breach databases...")
    breaches = check_breaches(email, proxies, headers)
    results['breaches'] = breaches
    
    # Phase 6: Username analysis
    print("\n🧩 Analyzing username...")
    analysis = analyze_username(username)
    results['username_analysis'] = analysis
    
    # Print summary
    print("\n" + "=" * 60)
    print("TRACE SUMMARY")
    print("=" * 60)
    confirmed = [k for k, v in results.items() if v == 'found' or (isinstance(v, dict) and v.get('exists'))]
    excluded = [k for k, v in results.items() if v == 'not_found' or (isinstance(v, dict) and not v.get('exists'))]
    
    print(f"Confirmed ({len(confirmed)}): {', '.join(confirmed) or 'none'}")
    print(f"Excluded ({len(excluded)}): {', '.join(excluded) or 'none'}")
    
    return results

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <email>")
        sys.exit(1)
    
    email = sys.argv[1]
    run_trace(email)
