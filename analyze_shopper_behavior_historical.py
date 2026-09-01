#!/usr/bin/env python3
"""
Historical Shopper Behavior Analysis Report

Fetches ALL search data from the platform's history, analyzes trends
by zip code over time, and sends an email report to stakeholders.

Usage:
    python analyze_shopper_behavior_historical.py
    python analyze_shopper_behavior_historical.py --dry-run  # Preview without sending
"""

import os
import sys
import argparse
from datetime import datetime, date
from collections import defaultdict, Counter
from typing import Dict, List, Any
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from email_notifier import EmailNotifier, BASE_EMAIL_TEMPLATE

# ============================================================================
# CONFIGURATION
# ============================================================================

# Reports go to the same people as the pipeline notifications, so the list is
# read from ADMIN_NOTIFICATION_EMAIL rather than duplicated here -- one secret
# to edit when someone joins or leaves. The fallback keeps the report working
# if that variable is ever missing.
_FALLBACK_RECIPIENTS = ["kontji@getyoudle.com", "johnita@getyoudle.com"]

RECIPIENT_EMAILS = [
    email.strip()
    for email in os.getenv("ADMIN_NOTIFICATION_EMAIL", "").split(",")
    if email.strip()
] or _FALLBACK_RECIPIENTS

from supabase import create_client, Client

# ============================================================================
# DATA FETCHING
# ============================================================================

def fetch_all_search_data() -> List[Dict[str, Any]]:
    """
    Fetch ALL search data from Supabase (no date filter).
    Paginates through results in batches of 1000.

    Returns:
        List of all search records
    """
    try:
        search_db_url = os.getenv("SEARCH_SUPABASE_URL") or os.getenv("SUPABASE_URL")
        search_db_key = os.getenv("SEARCH_SUPABASE_KEY") or os.getenv("SUPABASE_KEY")

        if not search_db_url or not search_db_key:
            print("Error: SEARCH_SUPABASE_URL and SEARCH_SUPABASE_KEY must be set")
            return []

        client: Client = create_client(search_db_url, search_db_key)

        print("Fetching all historical search data...")

        all_records = []
        batch_size = 1000
        offset = 0

        while True:
            response = client.table("search_log").select(
                "search_id, date, profile_id, search_query, zipcode, search_result_count, search_time"
            ).order("date").range(offset, offset + batch_size - 1).execute()

            batch = response.data or []
            all_records.extend(batch)

            if len(batch) < batch_size:
                break

            offset += batch_size
            print(f"  Fetched {len(all_records)} records so far...")

        print(f"Fetched {len(all_records)} total search records")
        return all_records

    except Exception as e:
        print(f"Error fetching data: {e}")
        import traceback
        traceback.print_exc()
        return []


# ============================================================================
# ANALYSIS HELPERS
# ============================================================================

def normalize_query(query: str) -> str:
    """Normalize search query for grouping similar searches."""
    normalized = query.lower().strip()
    normalized = re.sub(r'[^\w\s]', '', normalized)
    return normalized


def parse_date(d) -> date:
    """Parse a date value from a record."""
    if isinstance(d, date):
        return d
    return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()


def get_month_key(d: date) -> str:
    """Get YYYY-MM key from a date."""
    return d.strftime("%Y-%m")


def get_month_label(month_key: str) -> str:
    """Convert YYYY-MM to readable label like 'Mar 2025'."""
    dt = datetime.strptime(month_key, "%Y-%m")
    return dt.strftime("%b %Y")


# ============================================================================
# DATA ANALYSIS
# ============================================================================

def analyze_historical(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze all historical search behavior.

    Returns:
        Dictionary with comprehensive analysis results
    """
    if not records:
        return {"total_searches": 0}

    # Parse dates upfront
    for r in records:
        r["_date"] = parse_date(r.get("date", "2020-01-01"))
        r["_month"] = get_month_key(r["_date"])

    # --- Overall Stats ---
    total_searches = len(records)
    unique_users = len(set(r.get("profile_id", "") for r in records))
    unique_zips = set(r.get("zipcode", "") for r in records if r.get("zipcode"))
    all_dates = [r["_date"] for r in records]
    date_range = {"start": min(all_dates).isoformat(), "end": max(all_dates).isoformat()}

    # --- Monthly Trends ---
    monthly_searches = Counter()
    monthly_users = defaultdict(set)
    for r in records:
        month = r["_month"]
        monthly_searches[month] += 1
        pid = r.get("profile_id", "")
        if pid:
            monthly_users[month].add(pid)

    months_sorted = sorted(monthly_searches.keys())
    monthly_trends = []
    for m in months_sorted:
        monthly_trends.append({
            "month": m,
            "label": get_month_label(m),
            "searches": monthly_searches[m],
            "users": len(monthly_users[m])
        })

    # --- Top Searches All-Time ---
    query_counts = Counter()
    for r in records:
        q = r.get("search_query", "")
        if q:
            query_counts[normalize_query(q)] += 1

    top_searches = [
        {"query": q, "count": c}
        for q, c in query_counts.most_common(20)
    ]

    # --- Zip Code Deep Dive ---
    zip_data = defaultdict(lambda: {
        "total_searches": 0,
        "users": set(),
        "queries": Counter(),
        "monthly": Counter(),
        "first_seen": None,
        "last_seen": None,
        "avg_results": []
    })

    for r in records:
        zc = r.get("zipcode", "Unknown") or "Unknown"
        d = r["_date"]
        month = r["_month"]

        zip_data[zc]["total_searches"] += 1
        pid = r.get("profile_id", "")
        if pid:
            zip_data[zc]["users"].add(pid)

        q = r.get("search_query", "")
        if q:
            zip_data[zc]["queries"][normalize_query(q)] += 1

        zip_data[zc]["monthly"][month] += 1

        if zip_data[zc]["first_seen"] is None or d < zip_data[zc]["first_seen"]:
            zip_data[zc]["first_seen"] = d
        if zip_data[zc]["last_seen"] is None or d > zip_data[zc]["last_seen"]:
            zip_data[zc]["last_seen"] = d

        rc = r.get("search_result_count")
        if rc is not None:
            try:
                zip_data[zc]["avg_results"].append(int(float(rc)))
            except (ValueError, TypeError):
                pass

    zip_analysis = []
    for zc, data in sorted(zip_data.items(), key=lambda x: x[1]["total_searches"], reverse=True):
        top_queries = [{"query": q, "count": c} for q, c in data["queries"].most_common(10)]
        avg_results = (
            round(sum(data["avg_results"]) / len(data["avg_results"]), 1)
            if data["avg_results"] else 0
        )

        # Monthly activity for this zip
        zip_monthly = []
        for m in months_sorted:
            if data["monthly"][m] > 0:
                zip_monthly.append({"month": m, "label": get_month_label(m), "searches": data["monthly"][m]})

        zip_analysis.append({
            "zipcode": zc,
            "total_searches": data["total_searches"],
            "unique_users": len(data["users"]),
            "top_queries": top_queries,
            "avg_results": avg_results,
            "first_seen": data["first_seen"].isoformat() if data["first_seen"] else None,
            "last_seen": data["last_seen"].isoformat() if data["last_seen"] else None,
            "active_months": len([m for m in months_sorted if data["monthly"][m] > 0]),
            "monthly_activity": zip_monthly
        })

    # --- User Engagement ---
    user_search_counts = Counter()
    user_zips = defaultdict(set)
    for r in records:
        pid = r.get("profile_id", "")
        if pid:
            user_search_counts[pid] += 1
            zc = r.get("zipcode", "")
            if zc:
                user_zips[pid].add(zc)

    power_users = []
    for uid, count in user_search_counts.most_common(10):
        power_users.append({
            "user_id": uid[:8] + "...",
            "searches": count,
            "zip_codes": len(user_zips[uid])
        })

    return {
        "total_searches": total_searches,
        "unique_users": unique_users,
        "unique_zipcodes": len(unique_zips),
        "date_range": date_range,
        "monthly_trends": monthly_trends,
        "top_searches": top_searches,
        "zip_analysis": zip_analysis,
        "power_users": power_users,
    }


# ============================================================================
# REPORT GENERATION
# ============================================================================

def generate_report_html(analysis: Dict[str, Any]) -> str:
    """Generate HTML report from historical analysis results."""

    date_range_str = f"{analysis['date_range']['start']} to {analysis['date_range']['end']}"
    num_months = len(analysis["monthly_trends"])

    # --- Header Stats ---
    stats_html = f"""
    <div style="background-color: #f8f9fa; border-radius: 8px; padding: 20px; margin: 20px 0;">
        <h3 style="margin-top: 0; color: #333;">📊 All-Time Platform Overview</h3>
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px;">
            <div>
                <div style="color: #666; font-size: 14px;">Total Searches</div>
                <div style="font-size: 32px; font-weight: bold; color: #1a1a2e;">{analysis['total_searches']:,}</div>
            </div>
            <div>
                <div style="color: #666; font-size: 14px;">Unique Users</div>
                <div style="font-size: 32px; font-weight: bold; color: #1a1a2e;">{analysis['unique_users']:,}</div>
            </div>
            <div>
                <div style="color: #666; font-size: 14px;">Zip Codes Served</div>
                <div style="font-size: 32px; font-weight: bold; color: #1a1a2e;">{analysis['unique_zipcodes']}</div>
            </div>
            <div>
                <div style="color: #666; font-size: 14px;">Active Months</div>
                <div style="font-size: 32px; font-weight: bold; color: #1a1a2e;">{num_months}</div>
            </div>
        </div>
        <div style="margin-top: 10px; color: #999; font-size: 13px;">Data from {date_range_str}</div>
    </div>
    """

    # --- Monthly Trends Table ---
    monthly_html = """
    <div style="margin: 30px 0;">
        <h3 style="color: #333;">📈 Monthly Activity Trends</h3>
        <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
            <thead>
                <tr style="background-color: #1a1a2e; color: white;">
                    <th style="padding: 10px; text-align: left;">Month</th>
                    <th style="padding: 10px; text-align: right;">Searches</th>
                    <th style="padding: 10px; text-align: right;">Users</th>
                    <th style="padding: 10px; text-align: left;">Activity</th>
                </tr>
            </thead>
            <tbody>
    """

    max_searches = max((m["searches"] for m in analysis["monthly_trends"]), default=1)
    for i, m in enumerate(analysis["monthly_trends"]):
        bg = "#f8f9fa" if i % 2 == 0 else "white"
        bar_width = int((m["searches"] / max_searches) * 150)
        monthly_html += f"""
                <tr style="background-color: {bg};">
                    <td style="padding: 8px; color: #333; font-weight: 500;">{m['label']}</td>
                    <td style="padding: 8px; text-align: right; font-weight: bold;">{m['searches']:,}</td>
                    <td style="padding: 8px; text-align: right;">{m['users']:,}</td>
                    <td style="padding: 8px;">
                        <div style="background-color: #f93822; height: 14px; width: {bar_width}px; border-radius: 3px;"></div>
                    </td>
                </tr>
        """

    monthly_html += """
            </tbody>
        </table>
    </div>
    """

    # --- Top Searches All-Time ---
    top_searches_html = """
    <div style="margin: 30px 0;">
        <h3 style="color: #333;">🔥 Top Searches All-Time</h3>
        <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
            <thead>
                <tr style="background-color: #1a1a2e; color: white;">
                    <th style="padding: 10px; text-align: left;">Rank</th>
                    <th style="padding: 10px; text-align: left;">Search Query</th>
                    <th style="padding: 10px; text-align: right;">Count</th>
                </tr>
            </thead>
            <tbody>
    """

    for i, s in enumerate(analysis["top_searches"][:20], 1):
        bg = "#f8f9fa" if i % 2 == 0 else "white"
        top_searches_html += f"""
                <tr style="background-color: {bg};">
                    <td style="padding: 8px; font-weight: bold; color: #666;">#{i}</td>
                    <td style="padding: 8px; color: #333;">{s['query']}</td>
                    <td style="padding: 8px; text-align: right; font-weight: bold; color: #f93822;">{s['count']:,}</td>
                </tr>
        """

    top_searches_html += """
            </tbody>
        </table>
    </div>
    """

    # --- Zip Code Deep Dive ---
    zip_html = """
    <div style="margin: 30px 0;">
        <h3 style="color: #333;">📍 Zip Code Deep Dive</h3>
    """

    for zip_data in analysis["zip_analysis"][:15]:
        first_seen = zip_data["first_seen"] or "N/A"
        last_seen = zip_data["last_seen"] or "N/A"

        zip_html += f"""
        <div style="background-color: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; margin: 15px 0;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h4 style="margin: 0; color: #1a1a2e; font-size: 18px;">📌 {zip_data['zipcode']}</h4>
                <div style="text-align: right;">
                    <div style="font-size: 28px; font-weight: bold; color: #f93822;">{zip_data['total_searches']:,}</div>
                    <div style="font-size: 12px; color: #666;">total searches</div>
                </div>
            </div>

            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 15px; padding: 12px; background-color: #f8f9fa; border-radius: 4px;">
                <div>
                    <div style="color: #666; font-size: 12px;">Users</div>
                    <div style="font-weight: bold; font-size: 16px;">{zip_data['unique_users']}</div>
                </div>
                <div>
                    <div style="color: #666; font-size: 12px;">Avg Results</div>
                    <div style="font-weight: bold; font-size: 16px;">{zip_data['avg_results']}</div>
                </div>
                <div>
                    <div style="color: #666; font-size: 12px;">First Seen</div>
                    <div style="font-weight: bold; font-size: 14px;">{first_seen}</div>
                </div>
                <div>
                    <div style="color: #666; font-size: 12px;">Active Months</div>
                    <div style="font-weight: bold; font-size: 16px;">{zip_data['active_months']}</div>
                </div>
            </div>

            <div>
                <div style="font-size: 13px; color: #666; margin-bottom: 8px; font-weight: bold;">Top Searches:</div>
                <ol style="margin: 0; padding-left: 20px;">
        """

        for q in zip_data["top_queries"][:5]:
            zip_html += f"""
                    <li style="margin: 4px 0; color: #333;">
                        <span style="font-weight: 500;">{q['query']}</span>
                        <span style="color: #f93822; margin-left: 8px;">({q['count']:,})</span>
                    </li>
            """

        zip_html += """
                </ol>
            </div>
        </div>
        """

    zip_html += "</div>"

    # --- Power Users ---
    power_html = """
    <div style="margin: 30px 0;">
        <h3 style="color: #333;">👥 Most Active Users</h3>
        <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
            <thead>
                <tr style="background-color: #1a1a2e; color: white;">
                    <th style="padding: 10px; text-align: left;">Rank</th>
                    <th style="padding: 10px; text-align: left;">User ID</th>
                    <th style="padding: 10px; text-align: right;">Searches</th>
                    <th style="padding: 10px; text-align: right;">Zip Codes</th>
                </tr>
            </thead>
            <tbody>
    """

    for i, u in enumerate(analysis["power_users"][:10], 1):
        bg = "#f8f9fa" if i % 2 == 0 else "white"
        power_html += f"""
                <tr style="background-color: {bg};">
                    <td style="padding: 8px; font-weight: bold; color: #666;">#{i}</td>
                    <td style="padding: 8px; color: #333; font-family: monospace;">{u['user_id']}</td>
                    <td style="padding: 8px; text-align: right; font-weight: bold;">{u['searches']:,}</td>
                    <td style="padding: 8px; text-align: right;">{u['zip_codes']}</td>
                </tr>
        """

    power_html += """
            </tbody>
        </table>
    </div>
    """

    # --- Key Insights ---
    top_zip = analysis["zip_analysis"][0] if analysis["zip_analysis"] else None
    avg_per_month = analysis["total_searches"] / max(num_months, 1)

    insights_items = [
        f"Platform has processed <strong>{analysis['total_searches']:,}</strong> searches across <strong>{analysis['unique_zipcodes']}</strong> zip codes since launch",
        f"Average of <strong>{avg_per_month:,.0f}</strong> searches per month across <strong>{analysis['unique_users']:,}</strong> unique users",
    ]
    if top_zip:
        insights_items.append(
            f"Most active zip code: <strong>{top_zip['zipcode']}</strong> with {top_zip['total_searches']:,} searches from {top_zip['unique_users']} users"
        )

    # Growth insight
    if len(analysis["monthly_trends"]) >= 2:
        first_month = analysis["monthly_trends"][0]
        last_month = analysis["monthly_trends"][-1]
        if first_month["searches"] > 0:
            growth = ((last_month["searches"] - first_month["searches"]) / first_month["searches"]) * 100
            direction = "up" if growth > 0 else "down"
            insights_items.append(
                f"Search volume is <strong>{direction} {abs(growth):.0f}%</strong> from {first_month['label']} to {last_month['label']}"
            )

    insights_html = "<ul style='color: #666; line-height: 1.8;'>"
    for item in insights_items:
        insights_html += f"<li>{item}</li>"
    insights_html += "</ul>"

    # --- Assemble ---
    full_content = f"""
    <h2 style="color: #1a1a2e; margin-top: 0;">📈 Historical Shopper Behavior Report</h2>
    <p style="color: #666; font-size: 16px;">Complete platform search analysis from launch to present</p>

    {stats_html}
    {monthly_html}
    {top_searches_html}
    {zip_html}
    {power_html}

    <div style="margin-top: 40px; padding: 20px; background-color: #f8f9fa; border-radius: 8px;">
        <h4 style="margin-top: 0; color: #333;">💡 Key Insights</h4>
        {insights_html}
    </div>

    <p style="color: #999; font-size: 12px; margin-top: 30px; text-align: center;">
        Generated on {datetime.now().strftime('%Y-%m-%d at %I:%M %p CST')}
    </p>
    """

    return full_content


# ============================================================================
# SEND REPORT
# ============================================================================

def send_report(analysis: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """Send historical analysis report via email."""

    subject = f"📈 Historical Shopper Behavior Report - {analysis['date_range']['start']} to {analysis['date_range']['end']}"
    content_html = generate_report_html(analysis)
    full_html = BASE_EMAIL_TEMPLATE.format(
        subject=subject,
        content=content_html,
        year=datetime.now().year
    )

    if dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN - Email Preview")
        print("=" * 80)
        print(f"To: {', '.join(RECIPIENT_EMAILS)}")
        print(f"Subject: {subject}")
        print("\nHTML Content Preview:")
        print(content_html[:500] + "..." if len(content_html) > 500 else content_html)
        print("=" * 80)
        return {"success": True, "dry_run": True}

    notifier = EmailNotifier()
    result = notifier.send_notification(
        subject=subject,
        html_content=full_html,
        to_emails=RECIPIENT_EMAILS
    )

    return result


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate and send historical shopper behavior analysis report"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview report without sending email"
    )
    args = parser.parse_args()

    print("=" * 80)
    print("Historical Shopper Behavior Analysis")
    print("=" * 80)

    # Fetch ALL data
    records = fetch_all_search_data()

    if not records:
        print("Error: No data available for analysis")
        sys.exit(1)

    # Analyze
    print("\nAnalyzing historical search behavior...")
    analysis = analyze_historical(records)

    print(f"\nAnalysis complete:")
    print(f"  - Total searches: {analysis['total_searches']:,}")
    print(f"  - Unique users: {analysis['unique_users']:,}")
    print(f"  - Zip codes: {analysis['unique_zipcodes']}")
    print(f"  - Date range: {analysis['date_range']['start']} to {analysis['date_range']['end']}")
    print(f"  - Monthly data points: {len(analysis['monthly_trends'])}")

    # Send report
    print(f"\n{'Previewing' if args.dry_run else 'Sending'} report...")
    result = send_report(analysis, dry_run=args.dry_run)

    if result.get("success"):
        if args.dry_run:
            print("\n✓ Report preview generated successfully")
        else:
            print(f"\n✓ Report sent successfully to: {', '.join(RECIPIENT_EMAILS)}")
    else:
        print(f"\n✗ Error: {result.get('error', 'Unknown error')}")
        sys.exit(1)

    print("=" * 80)


if __name__ == "__main__":
    main()
