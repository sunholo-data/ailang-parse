#' ailangparse: R client and MCP server for the AILANG Parse document API
#'
#' Parses 13 document formats (DOCX, PPTX, XLSX, ODT, ODP, ODS, HTML, MD,
#' CSV, EPUB, PDF, PNG, JPG) into a structured Block ADT, supports
#' RFC 8628 device authorization, manages API keys, and exposes a drop-in
#' Unstructured.io compatibility layer.
#'
#' Quick start:
#' \preformatted{
#' library(ailangparse)
#' client <- DocParse$new()                       # auto-loads saved key
#' res    <- client$parse("report.docx")
#' res$blocks[[1]]
#' }
#'
#' To run as a Claude Desktop / Cursor / VS Code MCP stdio server:
#' \preformatted{
#' Rscript -e 'ailangparse::mcp()'
#' }
#'
#' @keywords internal
#' @importFrom R6 R6Class
#' @importFrom curl form_file
#' @importFrom utils browseURL
"_PACKAGE"
