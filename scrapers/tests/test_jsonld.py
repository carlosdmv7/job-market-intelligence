from __future__ import annotations

from datetime import UTC

from jmi_scrapers.jsonld import extract_jobposting_nodes, jobposting_to_fields

SAMPLE_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"WebSite","name":"Acme"}
</script>
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "JobPosting",
  "title": "Senior Data Engineer",
  "identifier": {"@type": "PropertyValue", "value": "JOB-42"},
  "datePosted": "2026-06-20",
  "validThrough": "2026-07-20T23:59:59Z",
  "employmentType": "FULL_TIME",
  "hiringOrganization": {"@type": "Organization", "name": "DataCorp"},
  "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress",
      "addressLocality": "Amsterdam", "addressRegion": "NH", "addressCountry": "NL"}},
  "baseSalary": {"@type": "MonetaryAmount", "currency": "EUR",
      "value": {"@type": "QuantitativeValue", "minValue": 70000, "maxValue": 90000, "unitText": "YEAR"}},
  "description": "<p>We use <b>dbt</b> and Snowflake. Visa sponsorship available.</p>",
  "url": "https://stepstone.de/jobs/JOB-42"
}
</script>
</head><body></body></html>
"""


def test_extracts_only_jobposting_node():
    nodes = extract_jobposting_nodes(SAMPLE_HTML)
    assert len(nodes) == 1
    assert nodes[0]["title"] == "Senior Data Engineer"


def test_maps_fields():
    fields = jobposting_to_fields(extract_jobposting_nodes(SAMPLE_HTML)[0])
    assert fields["title"] == "Senior Data Engineer"
    assert fields["company_name"] == "DataCorp"
    assert fields["source_job_id"] == "JOB-42"
    assert fields["location_raw"] == "Amsterdam, NH, NL"
    assert fields["country_code"] == "NL"
    assert fields["employment_type_raw"] == "FULL_TIME"
    assert fields["salary_raw"] == "EUR 70000-90000 year"
    assert fields["posted_at"].tzinfo == UTC
    assert fields["posted_at"].year == 2026 and fields["posted_at"].month == 6
    assert fields["valid_through"].day == 20


def test_handles_graph_and_lists():
    html = """<script type="application/ld+json">
    {"@graph":[{"@type":"Organization","name":"X"},
               {"@type":["JobPosting"],"title":"AE","hiringOrganization":"Y"}]}
    </script>"""
    nodes = extract_jobposting_nodes(html)
    assert len(nodes) == 1
    assert jobposting_to_fields(nodes[0])["company_name"] == "Y"


def test_ignores_malformed_blocks():
    html = '<script type="application/ld+json">{not valid json}</script>'
    assert extract_jobposting_nodes(html) == []
