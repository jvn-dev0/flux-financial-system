import glob
import re

html_files = glob.glob('user/*.html')

for filepath in html_files:
    if 'login.html' in filepath or 'signup.html' in filepath:
        continue

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Inject Click Monitor into the Auth check script
    auth_pattern = re.compile(r"(const session = JSON\.parse\(localStorage\.getItem\('userSession'\)\);\s*if \(!session\) \{[\s\S]*?window\.location\.href\s*=\s*['\"]login\.html['\"];(?:[\s\S]*?return;)?\s*\})")
    
    click_tracker_js = r"""\1

        // Initialize Click Tracking for ML
        if (!session.total_clicks) session.total_clicks = 0;
        if (!session.session_start_ms) session.session_start_ms = Date.now();
        
        document.body.addEventListener('click', () => {
            session.total_clicks++;
            localStorage.setItem('userSession', JSON.stringify(session));
        });
        
        // Calculate Clicks Per Minute dynamically
        function getClickRate() {
            const elapsedMinutes = (Date.now() - session.session_start_ms) / 60000;
            if (elapsedMinutes < 0.1) return session.total_clicks; // Return raw clicks if very short session
            return parseFloat((session.total_clicks / elapsedMinutes).toFixed(2));
        }
"""
    
    # Apply to auth block
    new_content = auth_pattern.sub(click_tracker_js, content)
    
    # 2. Add click_rate to fetch APIs in transfer_money.html and add_money.html
    if 'transfer_money.html' in filepath or 'add_money.html' in filepath:
        if 'pages_visited: session.pages_visited' in new_content:
            new_content = new_content.replace(
                "pages_visited: session.pages_visited",
                "pages_visited: session.pages_visited,\n                            click_rate: getClickRate()"
            )

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Patched ClickRate into {filepath}")

print("Frontend click tracking patched successfully.")
