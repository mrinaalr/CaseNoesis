"""Stage 1: Build candidates.json — platform → case IDs with per-platform counts."""
import sqlite3
import json
from collections import defaultdict

DB = "caselinker.db"
OUT = "ontology/q1/candidates.json"

PLATFORM_TYPE = {
    "Kik": "MessagingService",
    "Snapchat": "MessagingService",
    "Discord": "MessagingService",
    "WhatsApp": "MessagingService",
    "Telegram": "MessagingService",
    "Facebook Messenger": "MessagingService",
    "Skype": "MessagingService",
    "IRC": "MessagingService",
    "MeWe": "MessagingService",
    "AOL Instant Messenger": "MessagingService",
    "Facebook": "SocialMediaPlatform",
    "Twitter / X": "SocialMediaPlatform",
    "Instagram": "SocialMediaPlatform",
    "TikTok": "SocialMediaPlatform",
    "MySpace": "SocialMediaPlatform",
    "Dropbox": "FileHostingService",
    "Google Drive": "FileHostingService",
    "Mega.nz": "FileHostingService",
    "OneDrive": "FileHostingService",
    "Omegle": "AnonymousChatPlatform",
    "YouTube": "VideoStreamingPlatform",
    "Twitch": "VideoStreamingPlatform",
    "Webcam platform": "VideoStreamingPlatform",
    "Minecraft": "GamePlatform",
    "Xbox Live": "GamePlatform",
    "Roblox": "GamePlatform",
    "Fortnite": "GamePlatform",
    "PlayStation Network": "GamePlatform",
    "Craigslist": "ClassifiedsMarketplace",
    "Gen AI": "AIService",
    # Broad labels — keep but flag as generic
    "social media": "SocialMediaPlatform",
    "gaming": "GamePlatform",
    "email": "MessagingService",
    "internet": "Unknown",
    "dark web": "DarkWebService",
    "chat": "MessagingService",
    "other": "Unknown",
}

# Generics to exclude
GENERICS = {
    "online",
    "internet",
}

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT cases.id, j.value AS platform
        FROM cases, json_each(cases.platforms_used) AS j
        WHERE cases.platforms_used IS NOT NULL
    """)

    platform_to_cases = defaultdict(set)
    skipped_platforms = defaultdict(int)

    for row in cur.fetchall():
        p = row["platform"]
        if p.lower() in GENERICS or p.lower().startswith("unknown"):
            skipped_platforms[p] += 1
            continue
        if p not in PLATFORM_TYPE:
            # Unknown named platform — still include, type = Unknown
            pass
        platform_to_cases[p].add(row["id"])

    conn.close()

    # Build output grouped by platform_type
    by_type = defaultdict(list)
    for platform, case_ids in sorted(platform_to_cases.items(), key=lambda x: -len(x[1])):
        ptype = PLATFORM_TYPE.get(platform, "Unknown")
        by_type[ptype].append({
            "platform": platform,
            "platform_type": ptype,
            "case_count": len(case_ids),
            "case_ids": sorted(case_ids),
        })

    # Sort within each type by count desc
    for ptype in by_type:
        by_type[ptype].sort(key=lambda x: -x["case_count"])

    output = {
        "summary": {
            "total_candidate_cases": len({cid for cases in platform_to_cases.values() for cid in cases}),
            "total_platform_case_pairs": sum(len(v) for v in platform_to_cases.values()),
            "platforms_with_named_label": len(platform_to_cases),
            "skipped_generic_labels": dict(skipped_platforms),
        },
        "by_platform_type": dict(by_type),
        "flat": [
            {
                "platform": platform,
                "platform_type": PLATFORM_TYPE.get(platform, "Unknown"),
                "case_count": len(case_ids),
                "case_ids": sorted(case_ids),
            }
            for platform, case_ids in sorted(platform_to_cases.items(), key=lambda x: -len(x[1]))
        ],
    }

    with open(OUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {OUT}")
    print(f"\nSummary:")
    print(f"  Total candidate cases (distinct): {output['summary']['total_candidate_cases']}")
    print(f"  Total platform-case pairs:         {output['summary']['total_platform_case_pairs']}")
    print(f"  Named platforms:                   {output['summary']['platforms_with_named_label']}")
    print(f"\nPer-platform counts:")
    print(f"{'Platform':<30} {'Type':<30} {'Cases':>6}")
    print("-" * 70)
    for entry in output["flat"]:
        print(f"{entry['platform']:<30} {entry['platform_type']:<30} {entry['case_count']:>6}")

    print(f"\nSkipped generics:")
    for k, v in sorted(skipped_platforms.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v}")

if __name__ == "__main__":
    main()
