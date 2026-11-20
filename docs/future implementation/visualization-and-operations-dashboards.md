# Visualization and operations dashboards

**Status:** Planned. XenoDesk currently uses React, SVG, and CSS for product visualizations. Implement and verify each integration before selecting its checkbox in the submission form.

## Chart.js for Market Intelligence

Replace the `Sparkline` in [SourcingWorkspace.tsx](../../frontend/src/components/SourcingWorkspace.tsx) with a client-side Chart.js line chart. Use the existing monthly demand series from the sourcing snapshot. Show month and index in tooltips and label the vertical axis **Relative interest (0–100)**. Preserve missing months as gaps and keep the existing unavailable state. Provide a text summary and accessible data table alongside the canvas. Update the chart on research refresh and dispose of it on unmount.

Verify the chart against a known snapshot, including empty data, missing months, refreshed results, and mobile sizing. [Chart.js accessibility](https://www.chartjs.org/docs/latest/general/accessibility.html)

## D3.js for Customer Genome co-purchases

Add an authenticated [Genome API](../../backend/xenovarients/api/genome.py) endpoint that returns product-variant pairs and counts of qualifying orders in which repeat buyers purchased both variants. Aggregate existing PostgreSQL order items under the verified business scope. Bound the response with a date range and pair limit.

Add a D3 force layout in [GenomeOverview.tsx](../../frontend/src/components/GenomeOverview.tsx). Nodes represent variants and links represent co-purchase counts. Provide a minimum-count filter and an accessible table showing the same pairs. Stop the simulation when the view unmounts. The [optional Neo4j projection](mongodb-and-neo4j-storage.md) can supply the same response later.

Verify counts against known orders, check tenant isolation with two businesses, and test an empty result and keyboard access to the equivalent table. [D3 force layouts](https://d3js.org/d3-force)

## Grafana for operational metrics

Instrument [FastAPI startup](../../backend/xenovarients/main.py) and the [background worker](../../backend/xenovarients/jobs/worker.py). Scrape both processes with Prometheus through internal metrics endpoints. Record request latency and error rates, job failures, and Ollama fallbacks. Add MCP tool metrics when tool instrumentation is available. Use bounded labels such as route template, job type, and outcome.

Provision a Grafana dashboard for API traffic, worker health, and model fallbacks. Verify panels against a staging request, a failed job, and an Ollama fallback. [Grafana Prometheus data source](https://grafana.com/docs/grafana/latest/datasources/prometheus/)

## Kibana for log investigation

Use the existing [JSON logger](../../backend/xenovarients/core/logging.py) for API and worker events. Include request ID, route or job type, outcome, and service name. Where a request enqueues a job, propagate its correlation ID into the job context. Exclude raw prompts, customer records, credentials, and tool payloads before shipping logs.

Collect structured logs with Filebeat or Elastic Agent, send them to Elasticsearch, and configure a restricted Kibana data view with a retention policy. Verify an operator can locate a seeded failure by request ID and correlate it with the relevant job. [Elastic log collection](https://www.elastic.co/docs/reference/beats/filebeat/filebeat-input-filestream)
