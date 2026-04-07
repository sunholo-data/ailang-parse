#!/usr/bin/env Rscript
# AILANG Parse MCP stdio bridge entry point.
#
# Usage:
#   Rscript -e 'ailangparse::mcp()'         # preferred (uses installed package)
#   Rscript inst/scripts/ailang-parse-mcp.R # script form (also works after install)

suppressPackageStartupMessages(library(ailangparse))
ailangparse::mcp()
