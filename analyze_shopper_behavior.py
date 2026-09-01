#!/usr/bin/env python3
"""
Weekly Shopper Behavior Analysis Report

Fetches search data from the past 7 days, analyzes by zip code,
and sends an email report to stakeholders.

Usage:
    python analyze_shopper_behavior.py
    python analyze_shopper_behavior.py --dry-run  # Preview without sending
"""

import os
import sys
import argparse
from datetime import datetime, timedelta, date
from collections import defaultdict, Counter
from typing import Dict, List, Any, Optional
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

# Import Supabase
from supabase import create_client, Client

# ============================================================================
# DATA FETCHING
# ============================================================================

def fetch_search_data(days: int = 7) -> List[Dict[str, Any]]:
    """
    Fetch search data from Supabase for the past N days.

    Args:
        days: Number of days to fetch (default: 7)

    Returns:
        List of search records
    """
    try:
        # Get Supabase credentials for search database (youdle2 project)
        # Use separate env vars to distinguish from blog Supabase (youdeLLM project)
        search_db_url = os.getenv("SEARCH_SUPABASE_URL") or os.getenv("SUPABASE_URL")
        search_db_key = os.getenv("SEARCH_SUPABASE_KEY") or os.getenv("SUPABASE_KEY")

        if not search_db_url or not search_db_key:
            print("Error: SEARCH_SUPABASE_URL and SEARCH_SUPABASE_KEY must be set")
            return []

        # Create Supabase client
        client: Client = create_client(search_db_url, search_db_key)

        # Calculate date range (past N days)
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)

        print(f"Fetching search data from {start_date} to {end_date}...")

        # Query search_log table
        response = client.table("search_log").select(
            "search_id, date, profile_id, search_query, zipcode, search_result_count, search_time"
        ).gte("date", str(start_date)).lte("date", str(end_date)).execute()

        records = response.data or []
        print(f"Fetched {len(records)} search records")

        return records

    except Exception as e:
        print(f"Error fetching data: {e}")
        import traceback
        traceback.print_exc()
        return []


# ============================================================================
# DATA ANALYSIS
# ============================================================================

def normalize_query(query: str) -> str:
    """Normalize search query for grouping similar searches."""
    # Convert to lowercase, remove extra spaces
    normalized = query.lower().strip()
    # Remove punctuation
    normalized = re.sub(r'[^\w\s]', '', normalized)
    return normalized


def analyze_searches(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze search behavior and generate insights.

    Args:
        records: List of search records

    Returns:
        Dictionary with analysis results
    """
    if not records:
        return {
            "total_searches": 0,
            "unique_users": 0,
            "zip_codes": [],
            "top_searches": [],
            "searches_by_zip": {},
            "date_range": {"start": None, "end": None}
        }

    # Basic stats
    total_searches = len(records)
    unique_users = len(set(r.get('profile_id', '') for r in records))
    unique_zips = set(r.get('zipcode', '') for r in records if r.get('zipcode'))

    # Date range (handle both string and date objects)
    dates = []
    for r in records:
        d = r.get('date', '')
        if d:
            # Convert to string if it's a date object
            if isinstance(d, date):
                dates.append(d.isoformat())
            else:
                dates.append(str(d))

    date_range = {
        "start": min(dates) if dates else None,
        "end": max(dates) if dates else None
    }

    # Top searches overall (normalized)
    query_counts = Counter()
    for record in records:
        query = record.get('search_query', '')
        if query:
            normalized = normalize_query(query)
            query_counts[normalized] += 1

    top_searches = [
        {"query": query, "count": count}
        for query, count in query_counts.most_common(10)
    ]

    # Searches by zip code
    searches_by_zip = defaultdict(lambda: {
        "total_searches": 0,
        "unique_users": set(),
        "top_queries": Counter(),
        "avg_results": []
    })

    for record in records:
        zipcode = record.get('zipcode', 'Unknown')
        if not zipcode:
            zipcode = 'Unknown'

        searches_by_zip[zipcode]["total_searches"] += 1

        profile_id = record.get('profile_id', '')
        if profile_id:
            searches_by_zip[zipcode]["unique_users"].add(profile_id)

        query = record.get('search_query', '')
        if query:
            normalized = normalize_query(query)
            searches_by_zip[zipcode]["top_queries"][normalized] += 1

        result_count = record.get('search_result_count')
        if result_count is not None and isinstance(result_count, (int, float)):
            searches_by_zip[zipcode]["avg_results"].append(int(result_count))
        elif result_count and str(result_count).replace('.', '').isdigit():
            searches_by_zip[zipcode]["avg_results"].append(int(float(result_count)))

    # Convert to serializable format
    zip_analysis = []
    for zipcode, data in sorted(
        searches_by_zip.items(),
        key=lambda x: x[1]["total_searches"],
        reverse=True
    ):
        top_queries = [
            {"query": q, "count": c}
            for q, c in data["top_queries"].most_common(5)
        ]

        avg_results = (
            sum(data["avg_results"]) / len(data["avg_results"])
            if data["avg_results"] else 0
        )

        zip_analysis.append({
            "zipcode": zipcode,
            "total_searches": data["total_searches"],
            "unique_users": len(data["unique_users"]),
            "top_queries": top_queries,
            "avg_results": round(avg_results, 1)
        })

    return {
        "total_searches": total_searches,
        "unique_users": unique_users,
        "unique_zipcodes": len(unique_zips),
        "date_range": date_range,
        "top_searches": top_searches,
        "searches_by_zip": zip_analysis
    }


# ============================================================================
# REPORT GENERATION
# ============================================================================

def generate_report_html(analysis: Dict[str, Any]) -> str:
    """
    Generate HTML report from analysis results.

    Args:
        analysis: Analysis results dictionary

    Returns:
        HTML string
    """
    date_range_str = "N/A"
    if analysis["date_range"]["start"] and analysis["date_range"]["end"]:
        date_range_str = f"{analysis['date_range']['start']} to {analysis['date_range']['end']}"

    # Overall stats section
    stats_html = f"""
    <div style="background-color: #f8f9fa; border-radius: 8px; padding: 20px; margin: 20px 0;">
        <h3 style="margin-top: 0; color: #333;">📊 Weekly Overview</h3>
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
                <div style="color: #666; font-size: 14px;">Zip Codes</div>
                <div style="font-size: 32px; font-weight: bold; color: #1a1a2e;">{analysis['unique_zipcodes']}</div>
            </div>
            <div>
                <div style="color: #666; font-size: 14px;">Date Range</div>
                <div style="font-size: 14px; font-weight: bold; color: #1a1a2e; margin-top: 8px;">{date_range_str}</div>
            </div>
        </div>
    </div>
    """

    # Top searches overall
    top_searches_html = """
    <div style="margin: 30px 0;">
        <h3 style="color: #333;">🔥 Top Searches This Week</h3>
        <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
            <thead>
                <tr style="background-color: #1a1a2e; color: white;">
                    <th style="padding: 12px; text-align: left; border-radius: 4px 0 0 0;">Rank</th>
                    <th style="padding: 12px; text-align: left;">Search Query</th>
                    <th style="padding: 12px; text-align: right; border-radius: 0 4px 0 0;">Count</th>
                </tr>
            </thead>
            <tbody>
    """

    for i, search in enumerate(analysis["top_searches"][:10], 1):
        bg_color = "#f8f9fa" if i % 2 == 0 else "white"
        top_searches_html += f"""
                <tr style="background-color: {bg_color};">
                    <td style="padding: 10px; font-weight: bold; color: #666;">#{i}</td>
                    <td style="padding: 10px; color: #333;">{search['query']}</td>
                    <td style="padding: 10px; text-align: right; font-weight: bold; color: #f93822;">{search['count']}</td>
                </tr>
        """

    top_searches_html += """
            </tbody>
        </table>
    </div>
    """

    # Searches by zip code
    zip_html = """
    <div style="margin: 30px 0;">
        <h3 style="color: #333;">📍 Search Behavior by Zip Code</h3>
    """

    for zip_data in analysis["searches_by_zip"][:10]:  # Top 10 zip codes
        zip_html += f"""
        <div style="background-color: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; margin: 15px 0;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                <h4 style="margin: 0; color: #1a1a2e;">Zip Code: {zip_data['zipcode']}</h4>
                <div style="text-align: right;">
                    <div style="font-size: 24px; font-weight: bold; color: #f93822;">{zip_data['total_searches']}</div>
                    <div style="font-size: 12px; color: #666;">searches</div>
                </div>
            </div>

            <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 15px; padding: 10px; background-color: #f8f9fa; border-radius: 4px;">
                <div>
                    <span style="color: #666; font-size: 13px;">Unique Users:</span>
                    <span style="font-weight: bold; margin-left: 5px;">{zip_data['unique_users']}</span>
                </div>
                <div>
                    <span style="color: #666; font-size: 13px;">Avg Results:</span>
                    <span style="font-weight: bold; margin-left: 5px;">{zip_data['avg_results']}</span>
                </div>
            </div>

            <div>
                <div style="font-size: 13px; color: #666; margin-bottom: 8px; font-weight: bold;">Top Searches:</div>
                <ol style="margin: 0; padding-left: 20px;">
        """

        for query in zip_data['top_queries'][:5]:
            zip_html += f"""
                    <li style="margin: 5px 0; color: #333;">
                        <span style="font-weight: 500;">{query['query']}</span>
                        <span style="color: #f93822; margin-left: 8px;">({query['count']})</span>
                    </li>
            """

        zip_html += """
                </ol>
            </div>
        </div>
        """

    zip_html += "</div>"

    # Combine all sections
    full_content = f"""
    <h2 style="color: #1a1a2e; margin-top: 0;">📈 Weekly Shopper Behavior Report</h2>
    <p style="color: #666; font-size: 16px;">Analysis of search patterns and behavior from the past 7 days</p>

    {stats_html}
    {top_searches_html}
    {zip_html}

    <div style="margin-top: 40px; padding: 20px; background-color: #f8f9fa; border-radius: 8px;">
        <h4 style="margin-top: 0; color: #333;">💡 Key Insights</h4>
        <ul style="color: #666; line-height: 1.8;">
            <li>This report covers {analysis['total_searches']:,} searches across {analysis['unique_zipcodes']} zip codes</li>
            <li>Average of {analysis['total_searches'] / 7:.1f} searches per day</li>
            <li>Top zip code: <strong>{analysis['searches_by_zip'][0]['zipcode']}</strong> with {analysis['searches_by_zip'][0]['total_searches']} searches</li>
        </ul>
    </div>

    <p style="color: #999; font-size: 12px; margin-top: 30px; text-align: center;">
        Generated on {datetime.now().strftime('%Y-%m-%d at %I:%M %p CST')}
    </p>
    """

    return full_content


def send_report(analysis: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """
    Send analysis report via email.

    Args:
        analysis: Analysis results
        dry_run: If True, print report instead of sending

    Returns:
        Result dictionary
    """
    subject = f"📊 Weekly Shopper Behavior Report - Week of {analysis['date_range']['start']}"
    content_html = generate_report_html(analysis)
    full_html = BASE_EMAIL_TEMPLATE.format(
        subject=subject,
        content=content_html,
        year=datetime.now().year
    )

    if dry_run:
        print("\n" + "="*80)
        print("DRY RUN - Email Preview")
        print("="*80)
        print(f"To: {', '.join(RECIPIENT_EMAILS)}")
        print(f"Subject: {subject}")
        print("\nHTML Content Preview:")
        print(content_html[:500] + "..." if len(content_html) > 500 else content_html)
        print("="*80)
        return {"success": True, "dry_run": True}

    # Send via SMTP
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
        description="Generate and send weekly shopper behavior analysis report"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview report without sending email"
    )
    args = parser.parse_args()

    print("="*80)
    print("Weekly Shopper Behavior Analysis")
    print("="*80)

    # Fetch data
    records = fetch_search_data()

    if not records:
        print("Error: No data available for analysis")
        sys.exit(1)

    # Analyze
    print("\nAnalyzing search behavior...")
    analysis = analyze_searches(records)

    print(f"\nAnalysis complete:")
    print(f"  - Total searches: {analysis['total_searches']}")
    print(f"  - Unique users: {analysis['unique_users']}")
    print(f"  - Zip codes: {analysis['unique_zipcodes']}")
    print(f"  - Date range: {analysis['date_range']['start']} to {analysis['date_range']['end']}")

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

    print("="*80)


if __name__ == "__main__":
    main()
