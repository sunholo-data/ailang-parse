#' Internal HTTP helpers
#'
#' Thin wrapper around \pkg{httr2} that handles the AILANG Parse serve-API
#' response envelope (a JSON object with either a \code{result} field whose
#' value is a JSON-encoded string, or an \code{error} field).
#'
#' @keywords internal
#' @name http
NULL

.build_request <- function(base_url, path, api_key = NULL, timeout = 60) {
  req <- httr2::request(paste0(sub("/$", "", base_url), path))
  req <- httr2::req_timeout(req, timeout)
  req <- httr2::req_user_agent(req, "ailangparse-r/0.9.0")
  req <- httr2::req_error(req, is_error = function(resp) FALSE)
  if (!is.null(api_key) && nzchar(api_key)) {
    req <- httr2::req_headers(req, `x-api-key` = api_key)
  }
  req
}

.perform <- function(req) {
  resp <- httr2::req_perform(req)
  status <- httr2::resp_status(resp)
  body_text <- tryCatch(
    httr2::resp_body_string(resp),
    error = function(e) ""
  )
  .stop_for_status(status, body_text)
  headers <- tryCatch(httr2::resp_headers(resp), error = function(e) list())
  list(body = body_text, headers = headers)
}

# Resolve a user-supplied retry list against the defaults. Mirrors the Python
# SDK's RetryPolicy: the default does NOT retry (max_retries 0); the server
# returns 502/503/504 for transient AI failures and marks safe-to-retry 5xx
# with X-AilangParse-Replayable.
.resolve_retry <- function(retry = NULL) {
  d <- list(
    max_retries        = 0L,
    statuses           = c(502L, 503L, 504L),
    respect_replayable = TRUE,
    backoff_base       = 1,
    backoff_max        = 30
  )
  if (is.null(retry)) return(d)
  for (k in names(retry)) d[[k]] <- retry[[k]]
  d
}

# Apply the retry policy to a request via httr2::req_retry. No-op when
# max_retries <= 0. Delay before retry N is min(backoff_base * 2^(N-1),
# backoff_max). A 5xx carrying X-AilangParse-Replayable: true is treated as
# transient when respect_replayable is set.
.req_with_retry <- function(req, retry) {
  if (is.null(retry) || isTRUE(retry$max_retries <= 0)) return(req)
  statuses <- retry$statuses
  respect  <- isTRUE(retry$respect_replayable)
  base     <- retry$backoff_base
  max_d    <- retry$backoff_max
  httr2::req_retry(
    req,
    max_tries = as.integer(retry$max_retries) + 1L,
    is_transient = function(resp) {
      st <- httr2::resp_status(resp)
      if (st %in% statuses) return(TRUE)
      if (respect && st >= 500 && st < 600) {
        h <- tryCatch(httr2::resp_header(resp, "X-AilangParse-Replayable"),
                      error = function(e) NULL)
        if (!is.null(h) && identical(tolower(h), "true")) return(TRUE)
      }
      FALSE
    },
    backoff = function(attempt) min(base * 2^(attempt - 1), max_d)
  )
}

#' Unwrap a serve-API response envelope.
#'
#' On success returns the inner parsed object. On error raises an
#' \code{ailang_docparse_error}.
#'
#' @param body_text Raw JSON text returned by the API.
#' @return A parsed list (the inner result).
#' @keywords internal
.is_auth_error_message <- function(msg) {
  if (is.null(msg) || !nzchar(msg)) return(FALSE)
  m <- tolower(msg)
  grepl("invalid or expired api key", m, fixed = TRUE) ||
    grepl("invalid api key", m, fixed = TRUE) ||
    grepl("missing api key", m, fixed = TRUE) ||
    grepl("unauthorized", m, fixed = TRUE) ||
    grepl("api key required", m, fixed = TRUE)
}

.raise_envelope_error <- function(msg, suggested_fix = "",
                                  details = NULL, request_id = "") {
  if (.is_auth_error_message(msg)) {
    stop(.auth_error(msg))
  }
  stop(.docparse_error(msg, suggested_fix = suggested_fix,
                       details = details, request_id = request_id))
}

.unwrap <- function(body_text) {
  if (!nzchar(body_text)) return(list())
  outer <- tryCatch(
    jsonlite::fromJSON(body_text, simplifyVector = FALSE),
    error = function(e) {
      stop(.docparse_error(sprintf("Invalid JSON response: %s", conditionMessage(e))))
    }
  )
  if (!is.null(outer$error) && length(outer$error) > 0L) {
    err <- outer$error
    if (is.character(err)) {
      # Legacy error: {error: "CODE", message: "...", suggested_fix: "..."}
      msg <- if (!is.null(outer$message) && nzchar(outer$message)) outer$message else err
      fix <- if (!is.null(outer$suggested_fix)) .s(outer$suggested_fix) else ""
      .raise_envelope_error(msg, suggested_fix = fix)
    }
    if (is.list(err)) {
      # Structured dict error: {error: {code, message, details, ...}, request_id}
      msg <- if (!is.null(err$message)) .s(err$message) else as.character(err)
      fix <- if (!is.null(err$suggested_fix)) .s(err$suggested_fix) else ""
      details <- err$details
      request_id <- if (!is.null(outer$request_id)) .s(outer$request_id) else ""
      .raise_envelope_error(msg, suggested_fix = fix,
                            details = details, request_id = request_id)
    }
    # Unknown error shape — return for caller handling
    return(outer)
  }
  result_str <- outer$result
  if (is.null(result_str) || !nzchar(result_str)) return(outer)
  inner <- tryCatch(
    jsonlite::fromJSON(result_str, simplifyVector = FALSE),
    error = function(e) list(raw = result_str)
  )
  if (is.list(inner) && !is.null(inner$error) && length(inner$error) > 0L) {
    err <- inner$error
    if (is.list(err)) {
      msg <- if (!is.null(err$message)) .s(err$message) else as.character(err)
      fix <- if (!is.null(err$suggested_fix)) .s(err$suggested_fix) else ""
      details <- err$details
      request_id <- if (!is.null(inner$request_id)) .s(inner$request_id) else ""
      .raise_envelope_error(msg, suggested_fix = fix,
                            details = details, request_id = request_id)
    }
    .raise_envelope_error(as.character(err))
  }
  inner
}

#' Internal: GET or POST to a JSON API endpoint and unwrap the envelope.
#' @keywords internal
.call <- function(base_url, path, method = "GET",
                  api_key = NULL, args = NULL, timeout = 60) {
  req <- .build_request(base_url, path, api_key, timeout)
  if (identical(method, "GET")) {
    req <- httr2::req_method(req, "GET")
  } else {
    body <- if (is.null(args)) list() else list(args = args)
    req <- httr2::req_body_json(req, body, auto_unbox = FALSE)
  }
  .unwrap(.perform(req)$body)
}
