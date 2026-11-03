"""Calculate actual returned DeepSeek token usage and public-price RMB amounts."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.usage_cost import reconcile_usage, markdown_report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ledger', type=Path, help='JSON containing requests[] with actual returned usage')
    parser.add_argument('--output', type=Path, required=True, help='Output JSON; Markdown is written alongside')
    parser.add_argument('--holiday', action='append', default=[], help='Chinese statutory holiday YYYY-MM-DD, repeatable')
    args=parser.parse_args()
    report=reconcile_usage(json.loads(args.ledger.read_text('utf-8-sig')), args.holiday)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    args.output.with_suffix('.md').write_text(markdown_report(report),'utf-8')
    print(json.dumps({k:report[k] for k in ('requestCount','usageComplete','costCoverageComplete','rmbAtPublishedRates','knownRequestsRmbRange')},ensure_ascii=True))


if __name__=='__main__':main()
