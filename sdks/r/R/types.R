#' AILANG Parse types: Block ADT, Cell, ParseResult and friends
#'
#' Each block returned by the API is converted into an S3 list whose class
#' vector is \code{c("ailang_block_<type>", "ailang_block")}. Tables also
#' implement \code{as.data.frame()} for ergonomic R consumption.
#'
#' @keywords internal
#' @name types
NULL

# ── helpers ──────────────────────────────────────────────────────────────────

.s <- function(x, default = "") {
  if (is.null(x)) default else as.character(x)
}
.i <- function(x, default = 0L) {
  if (is.null(x)) default else as.integer(x)
}
.b <- function(x, default = FALSE) {
  if (is.null(x)) default else isTRUE(as.logical(x))
}

# ── Cell ─────────────────────────────────────────────────────────────────────

.cell_from_raw <- function(raw) {
  if (is.character(raw) && length(raw) == 1L) {
    return(list(text = raw, col_span = 1L, merged = FALSE))
  }
  if (is.list(raw)) {
    return(list(
      text     = .s(raw$text),
      col_span = .i(raw$colSpan, 1L),
      merged   = .b(raw$merged)
    ))
  }
  list(text = as.character(raw), col_span = 1L, merged = FALSE)
}

# ── Block ────────────────────────────────────────────────────────────────────

#' Convert a raw API block list into a typed Block S3 object.
#' @keywords internal
.block_from_list <- function(d) {
  if (!is.list(d)) return(NULL)
  type <- .s(d$type)
  block <- list(
    type          = type,
    text          = .s(d$text),
    level         = .i(d$level),
    style         = .s(d$style),
    change_type   = .s(d$changeType),
    author        = .s(d$author),
    date          = .s(d$date),
    description   = .s(d$description),
    transcription = .s(d$transcription),
    mime          = .s(d$mime),
    data_length   = .i(d$dataLength),
    kind          = .s(d$kind),
    ordered       = .b(d$ordered),
    items         = if (is.null(d$items)) character() else vapply(d$items, .s, character(1)),
    headers       = lapply(if (is.null(d$headers)) list() else d$headers, .cell_from_raw),
    rows          = lapply(
      if (is.null(d$rows)) list() else d$rows,
      function(row) lapply(row, .cell_from_raw)
    ),
    children      = lapply(
      if (is.null(d$blocks)) list() else d$blocks,
      .block_from_list
    )
  )
  subclass <- if (nzchar(type)) paste0("ailang_block_", type) else "ailang_block_unknown"
  class(block) <- c(subclass, "ailang_block")
  block
}

#' @export
format.ailang_block <- function(x, ...) {
  switch(
    x$type,
    "heading" = sprintf("H%d: %s", x$level, x$text),
    "table"   = sprintf("Table: %d cols x %d rows", length(x$headers), length(x$rows)),
    "list"    = sprintf("List (%s, %d items)",
                        if (x$ordered) "ordered" else "unordered", length(x$items)),
    "image"   = sprintf("Image (%s, %d bytes)", x$mime, x$data_length),
    "audio"   = sprintf("Audio (%s, %d bytes)", x$mime, x$data_length),
    "video"   = sprintf("Video (%s, %d bytes)", x$mime, x$data_length),
    "section" = sprintf("Section (%s, %d children)", x$kind, length(x$children)),
    "change"  = sprintf("%s by %s: %s", x$change_type, x$author, x$text),
    sprintf("%s: %s", x$type, substr(x$text, 1L, 80L))
  )
}

#' @export
print.ailang_block <- function(x, ...) {
  cat("<ailang_block ", x$type, "> ", format(x), "\n", sep = "")
  invisible(x)
}

#' @export
as.data.frame.ailang_block_table <- function(x, row.names = NULL,
                                             optional = FALSE, ...) {
  header_text <- vapply(x$headers, function(c) c$text, character(1))
  if (length(x$rows) == 0L) {
    df <- as.data.frame(
      matrix(character(), nrow = 0L, ncol = length(header_text)),
      stringsAsFactors = FALSE
    )
    if (length(header_text) > 0L) names(df) <- header_text
    return(df)
  }
  rows_text <- lapply(x$rows, function(row) {
    vapply(row, function(c) c$text, character(1))
  })
  ncols <- max(length(header_text), max(lengths(rows_text)))
  if (length(header_text) < ncols) {
    header_text <- c(header_text, rep("", ncols - length(header_text)))
  }
  rows_text <- lapply(rows_text, function(r) {
    if (length(r) < ncols) c(r, rep("", ncols - length(r))) else r
  })
  m <- do.call(rbind, rows_text)
  df <- as.data.frame(m, stringsAsFactors = FALSE)
  names(df) <- header_text
  df
}

# ── Metadata, Summary, ParseResult ───────────────────────────────────────────

.doc_metadata_from_list <- function(d) {
  if (!is.list(d)) d <- list()
  list(
    title      = .s(d$title),
    author     = .s(d$author),
    created    = .s(d$created),
    modified   = .s(d$modified),
    page_count = .i(d$pageCount)
  )
}

.summary_from_list <- function(d) {
  if (!is.list(d)) d <- list()
  list(
    total_blocks = .i(d$totalBlocks),
    headings     = .i(d$headings),
    tables       = .i(d$tables),
    images       = .i(d$images),
    changes      = .i(d$changes)
  )
}

#' Convert a raw API response into a ParseResult S3 object.
#' @keywords internal
.parse_result_from_list <- function(d) {
  if (!is.list(d)) d <- list()
  blocks <- lapply(if (is.null(d$blocks)) list() else d$blocks, .block_from_list)
  blocks <- Filter(Negate(is.null), blocks)
  res <- list(
    status   = .s(d$status),
    filename = .s(d$filename),
    format   = .s(d$format),
    blocks   = blocks,
    metadata = .doc_metadata_from_list(d$metadata),
    summary  = .summary_from_list(d$summary)
  )
  class(res) <- "ailang_parse_result"
  res
}

#' @export
print.ailang_parse_result <- function(x, ...) {
  cat("<ailang_parse_result>\n")
  cat("  status:   ", x$status, "\n", sep = "")
  cat("  filename: ", x$filename, "\n", sep = "")
  cat("  format:   ", x$format, "\n", sep = "")
  cat("  blocks:   ", length(x$blocks), "\n", sep = "")
  if (nzchar(x$metadata$title)) {
    cat("  title:    ", x$metadata$title, "\n", sep = "")
  }
  invisible(x)
}

# ── Health, Formats, Key types ───────────────────────────────────────────────

.health_result_from_list <- function(d) {
  if (!is.list(d)) d <- list()
  list(
    status           = .s(d$status),
    version          = .s(d$version),
    service          = .s(d$service),
    formats_parse    = .i(d$formats_parse),
    formats_generate = .i(d$formats_generate)
  )
}

.formats_result_from_list <- function(d) {
  if (!is.list(d)) d <- list()
  to_chr <- function(x) if (is.null(x)) character() else vapply(x, .s, character(1))
  list(
    parse       = to_chr(d$parse),
    generate    = to_chr(d$generate),
    ai_required = to_chr(d$ai_required)
  )
}

.quota_from_list <- function(d) {
  if (!is.list(d)) d <- list()
  list(
    requests_per_day      = .i(d$requestsPerDay),
    requests_per_month    = .i(d$requestsPerMonth),
    ai_limit_per_request  = .i(d$aiLimitPerRequest),
    fs_limit_per_request  = .i(d$fsLimitPerRequest)
  )
}

.key_info_from_list <- function(d) {
  if (!is.list(d)) d <- list()
  list(
    status  = .s(d$status),
    key     = .s(d$key),
    key_id  = .s(d$keyId),
    label   = .s(d$label),
    tier    = .s(d$tier),
    created = .s(d$created),
    quota   = .quota_from_list(d$quota)
  )
}

.usage_from_list <- function(d) {
  if (!is.list(d)) d <- list()
  list(
    requests_today      = .i(d$requestsToday),
    requests_this_month = .i(d$requestsThisMonth),
    total_requests      = .i(d$totalRequests)
  )
}

.usage_info_from_list <- function(d) {
  if (!is.list(d)) d <- list()
  list(
    status = .s(d$status),
    key_id = .s(d$keyId),
    tier   = .s(d$tier),
    usage  = .usage_from_list(d$usage),
    quota  = .quota_from_list(d$quota)
  )
}

# ── Unstructured compat element ──────────────────────────────────────────────

.element_metadata_from_list <- function(d) {
  if (!is.list(d)) d <- list()
  list(
    filename        = .s(d$filename),
    filetype        = .s(d$filetype),
    category_depth  = .i(d$category_depth),
    image_mime_type = .s(d$image_mime_type),
    text_as_html    = .s(d$text_as_html)
  )
}

.element_from_list <- function(d) {
  if (!is.list(d)) d <- list()
  list(
    type       = .s(d$type),
    element_id = .s(d$element_id),
    text       = .s(d$text),
    metadata   = .element_metadata_from_list(d$metadata)
  )
}
