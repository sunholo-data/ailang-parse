#' AILANG Parse API client
#'
#' R6 class wrapping the hosted AILANG Parse REST API. Provides parsing,
#' health/format introspection, RFC 8628 device authorization and key
#' management (via \code{$keys}).
#'
#' API key resolution order:
#' \enumerate{
#'   \item Explicit \code{api_key} argument to \code{$new()}.
#'   \item \code{DOCPARSE_API_KEY} environment variable.
#'   \item Saved credentials in
#'         \code{~/.config/ailang-parse/credentials.json}
#'         (matched against \code{base_url}).
#' }
#'
#' @examples
#' \dontrun{
#' client <- DocParse$new()                       # auto-loads saved key
#' res    <- client$parse("report.docx")
#' for (b in res$blocks) print(b)
#' }
#'
#' @export
DocParse <- R6::R6Class(
  "DocParse",
  public = list(
    #' @field base_url Hosted API endpoint (no trailing slash).
    base_url = NULL,
    #' @field timeout Per-request timeout in seconds.
    timeout = NULL,
    #' @field api_key Active API key, or \code{""} if unauthenticated.
    api_key = NULL,
    #' @field key_id Stored key id, populated from saved credentials or
    #'   \code{$device_auth()}. Used by \code{$key_info()} when no explicit
    #'   id is passed.
    key_id = NULL,
    #' @field keys A \code{KeyManager} bound to this client.
    keys = NULL,

    #' @description Construct a new client.
    #' @param api_key Optional API key. If empty, the env var and saved
    #'   credentials are consulted in that order.
    #' @param base_url Hosted API endpoint.
    #' @param timeout Per-request timeout in seconds.
    initialize = function(api_key = NULL,
                          base_url = default_base_url(),
                          timeout = 60) {
      self$base_url <- sub("/$", "", base_url)
      self$timeout  <- timeout

      key <- if (is.null(api_key)) "" else api_key
      kid <- ""
      if (!nzchar(key)) {
        key <- Sys.getenv("DOCPARSE_API_KEY", unset = "")
      }
      if (!nzchar(key)) {
        saved <- load_saved_key(self$base_url)
        if (!is.null(saved)) {
          key <- saved$api_key
          if (!is.null(saved$key_id)) kid <- saved$key_id
        }
      }
      self$api_key <- key
      self$key_id  <- kid
      self$keys <- KeyManager$new(self)
      invisible(self)
    },

    #' @description Parse a document by sample ID or server-side filepath.
    #'   To upload a local file, use \code{$parse_file()}.
    #'   To parse from a signed URL, use \code{$parse_url()}.
    #' @param filepath Sample ID or server-side filepath.
    #' @param output_format One of \code{"blocks"}, \code{"markdown"},
    #'   \code{"html"}.
    #' @param source_url Optional HTTPS signed URL (GCS, S3, Azure Blob)
    #'   to fetch the document from server-side.
    #' @return A \code{ailang_parse_result} S3 list with a
    #'   \code{"response_meta"} attribute containing quota/tier headers.
    parse = function(filepath, output_format = "blocks", source_url = NULL) {
      body <- list(
        filepath     = jsonlite::unbox(filepath),
        outputFormat = jsonlite::unbox(output_format)
      )
      if (!is.null(source_url)) {
        body$sourceUrl <- jsonlite::unbox(source_url)
      }
      if (nzchar(self$api_key)) {
        body$apiKey <- jsonlite::unbox(self$api_key)
      }
      req <- .build_request(self$base_url, "/api/v1/parse",
                            self$api_key, self$timeout)
      req <- httr2::req_body_json(req, body, auto_unbox = FALSE)
      resp <- .perform(req)
      result <- .build_parse_result(.unwrap(resp$body), output_format)
      attr(result, "response_meta") <- .response_meta_from_headers(resp$headers)
      result
    },

    #' @description Upload a local file (multipart) and parse it.
    #' @param filepath Path to a local file.
    #' @param output_format One of \code{"blocks"}, \code{"markdown"},
    #'   \code{"html"}.
    #' @return A \code{ailang_parse_result} S3 list with a
    #'   \code{"response_meta"} attribute containing quota/tier headers.
    parse_file = function(filepath, output_format = "blocks") {
      stopifnot(file.exists(filepath))
      req <- .build_request(self$base_url, "/api/v1/parse",
                            self$api_key, self$timeout)
      req <- httr2::req_body_multipart(
        req,
        filepath     = curl::form_file(filepath, name = basename(filepath)),
        outputFormat = output_format,
        apiKey       = self$api_key
      )
      resp <- .perform(req)
      result <- .build_parse_result(.unwrap(resp$body), output_format)
      attr(result, "response_meta") <- .response_meta_from_headers(resp$headers)
      result
    },

    #' @description Parse a document from a signed URL (GCS, S3, Azure
    #'   Blob, etc.) without uploading a local file.
    #' @param url HTTPS signed URL pointing to the document.
    #' @param output_format One of \code{"blocks"}, \code{"markdown"},
    #'   \code{"html"}.
    #' @return A \code{ailang_parse_result} S3 list with a
    #'   \code{"response_meta"} attribute containing quota/tier headers.
    #' @export
    parse_url = function(url, output_format = "blocks") {
      self$parse(filepath = "", output_format = output_format, source_url = url)
    },

    #' @description Check API health.
    #' @return A list with \code{status}, \code{version}, etc.
    health = function() {
      .health_result_from_list(
        .call(self$base_url, "/api/v1/health", "GET",
              self$api_key, timeout = self$timeout)
      )
    },

    #' @description List supported formats.
    #' @return A list with \code{parse}, \code{generate}, \code{ai_required}.
    formats = function() {
      .formats_result_from_list(
        .call(self$base_url, "/api/v1/formats", "GET",
              self$api_key, timeout = self$timeout)
      )
    },

    #' @description Return live usage + quota info for the *currently
    #'   configured* key.
    #'
    #' Resolution order for the key id:
    #' \enumerate{
    #'   \item \code{self$key_id} (set by saved credentials or
    #'         \code{$device_auth()}).
    #'   \item Otherwise call \code{self$keys$list("")} and find the entry
    #'         whose \code{key} field matches \code{self$api_key}. The
    #'         resolved id is cached for future calls.
    #' }
    #'
    #' Stops if neither path can resolve a key id -- the AILANG API has no
    #' \code{/auth/whoami} endpoint, so the SDK needs either a saved
    #' credential or a list-able admin key.
    key_info = function() {
      if (!nzchar(.s(self$api_key))) {
        stop(.docparse_error("client$key_info() requires an API key on the client"))
      }
      if (!nzchar(.s(self$key_id))) {
        listing <- tryCatch(
          self$keys$list(""),
          error = function(e) {
            stop(.docparse_error(paste0(
              "client$key_info() requires a saved credential or device_auth ",
              "flow -- pass key_id explicitly to client$keys$usage(): ",
              conditionMessage(e)
            )))
          }
        )
        keys <- if (is.list(listing) && !is.null(listing$keys)) listing$keys else list()
        for (k in keys) {
          if (!is.list(k)) next
          k_field <- .s(k$key)
          if (!nzchar(k_field)) k_field <- .s(k$api_key)
          if (identical(k_field, self$api_key)) {
            kid <- .s(k$key_id)
            if (!nzchar(kid)) kid <- .s(k$keyId)
            if (nzchar(kid)) {
              self$key_id <- kid
              break
            }
          }
        }
        if (!nzchar(.s(self$key_id))) {
          stop(.docparse_error(paste0(
            "client$key_info() could not resolve key_id -- pass it ",
            "explicitly to client$keys$usage()"
          )))
        }
      }
      self$keys$usage(self$key_id)
    },

    #' @description Run the RFC 8628 device-authorization flow to obtain an
    #'   API key. Prints the verification URL, optionally opens a browser,
    #'   then polls until approved. On success the key is stored on this
    #'   client and persisted to disk via \code{save_key()}.
    #' @param label Human-readable label to attach to the new key.
    #' @param scope Requested scope (default \code{"parse"}).
    #' @param open_browser Whether to call \code{utils::browseURL()}.
    #' @param poll_interval Override the server-suggested poll interval (s).
    #' @param timeout Maximum total wait in seconds.
    #' @return A list with \code{api_key}, \code{key_id}, \code{tier},
    #'   \code{label}.
    device_auth = function(label = "default",
                           scope = "parse",
                           open_browser = TRUE,
                           poll_interval = NULL,
                           timeout = 900) {
      # Step 1: request device code
      req <- .build_request(self$base_url, "/api/v1/auth/device",
                            api_key = NULL, timeout = 30)
      req <- httr2::req_body_json(
        req,
        list(label = jsonlite::unbox(label),
             scope = jsonlite::unbox(scope))
      )
      data <- .unwrap(.perform(req)$body)

      device_code <- .s(data$device_code)
      user_code   <- .s(data$user_code)
      verify_url  <- .s(data$verification_url)
      interval    <- if (!is.null(poll_interval)) poll_interval
                     else if (!is.null(data$interval)) as.numeric(data$interval)
                     else 5

      message("\n  Authorize this device:")
      message("  ", verify_url)
      message("  Code: ", user_code, "\n")

      if (isTRUE(open_browser) && nzchar(verify_url)) {
        try(utils::browseURL(verify_url), silent = TRUE)
      }

      deadline <- Sys.time() + timeout
      repeat {
        if (Sys.time() >= deadline) {
          stop(.docparse_error("Device authorization timed out"))
        }
        Sys.sleep(interval)
        poll_req <- .build_request(self$base_url, "/api/v1/auth/device/poll",
                                   api_key = NULL, timeout = 30)
        poll_req <- httr2::req_body_json(
          poll_req,
          list(deviceCode = jsonlite::unbox(device_code))
        )
        poll <- .unwrap(.perform(poll_req)$body)

        if (identical(.s(poll$status), "approved") && nzchar(.s(poll$api_key))) {
          self$api_key <- poll$api_key
          self$key_id  <- .s(poll$key_id)
          result <- list(
            api_key          = .s(poll$api_key),
            key_id           = .s(poll$key_id),
            tier             = .s(poll$tier, "free"),
            label            = if (nzchar(.s(poll$label))) .s(poll$label) else label,
            verification_url = verify_url,
            poll_url         = paste0(self$base_url, "/api/v1/auth/device/poll")
          )
          save_key(
            api_key  = result$api_key,
            base_url = self$base_url,
            key_id   = result$key_id,
            tier     = result$tier,
            label    = result$label
          )
          return(result)
        }

        err <- poll$error
        if (!is.null(err) && length(err) > 0L) {
          if (is.list(err)) {
            code <- .s(err$code)
            if (nzchar(code) && code != "AUTHORIZATION_PENDING") {
              stop(.docparse_error(.s(err$message, code)))
            }
          } else {
            err_str <- as.character(err)
            if (nzchar(err_str) && err_str != "AUTHORIZATION_PENDING") {
              stop(.docparse_error(.s(poll$message, err_str)))
            }
          }
        }
      }
    }
  )
)
