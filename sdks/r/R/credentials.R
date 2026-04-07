#' Credential storage helpers
#'
#' Mirrors the cross-SDK credential format used by the Python, JavaScript and
#' Go AILANG Parse clients so a key saved in any one of them is usable from
#' any other. The on-disk file is JSON with these fields:
#' \code{api_key}, \code{base_url}, \code{key_id}, \code{tier}, \code{label}.
#'
#' Storage location:
#' \itemize{
#'   \item Linux/macOS: \code{$XDG_CONFIG_HOME/ailang-parse/credentials.json}
#'         (default \code{~/.config/ailang-parse/credentials.json}).
#'   \item Windows: \code{\%APPDATA\%/ailang-parse/credentials.json}.
#' }
#'
#' On Unix the file is written with mode \code{0600} and the directory with
#' \code{0700}.
#'
#' @name credentials
NULL

#' @describeIn credentials Default hosted API endpoint.
#' @return \code{default_base_url()} returns a single string.
#' @examples
#' default_base_url()
#' @export
default_base_url <- function() {
  "https://docparse.ailang.sunholo.com"
}

.config_dir_name <- "ailang-parse"
.credentials_file <- "credentials.json"

.config_dir <- function() {
  if (.Platform$OS.type == "windows") {
    base <- Sys.getenv("APPDATA")
    if (!nzchar(base)) {
      base <- file.path(Sys.getenv("USERPROFILE"), "AppData", "Roaming")
    }
  } else {
    base <- Sys.getenv("XDG_CONFIG_HOME")
    if (!nzchar(base)) {
      base <- file.path(path.expand("~"), ".config")
    }
  }
  file.path(base, .config_dir_name)
}

#' @describeIn credentials Absolute path to the credentials file (whether or
#'   not it exists).
#' @examples
#' credentials_path()
#' @export
credentials_path <- function() {
  file.path(.config_dir(), .credentials_file)
}

.read_credentials_file <- function() {
  path <- credentials_path()
  if (!file.exists(path)) return(NULL)
  data <- tryCatch(
    jsonlite::fromJSON(path, simplifyVector = TRUE),
    error = function(e) NULL
  )
  if (!is.list(data)) return(NULL)
  key <- data$api_key
  if (!is.character(key) || length(key) != 1L || !startsWith(key, "dp_")) {
    return(NULL)
  }
  data
}

#' @describeIn credentials Load saved credentials matching \code{base_url}, or
#'   \code{NULL} if no compatible record exists.
#' @param base_url Base URL the saved key must match.
#' @examples
#' \dontrun{
#' load_saved_key()
#' }
#' @export
load_saved_key <- function(base_url = default_base_url()) {
  data <- .read_credentials_file()
  if (is.null(data)) return(NULL)
  saved_url <- if (is.null(data$base_url) || !nzchar(data$base_url)) {
    default_base_url()
  } else {
    data$base_url
  }
  if (!identical(saved_url, base_url)) return(NULL)
  data
}

#' @describeIn credentials Persist credentials to disk with restrictive
#'   permissions. Returns the path written, invisibly.
#' @param api_key API key string (must start with \code{dp_}).
#' @param key_id Opaque key identifier returned by the device-auth flow.
#' @param tier Plan tier (\code{"free"}, \code{"pro"}, ...).
#' @param label Human-readable label for the key.
#' @examples
#' \dontrun{
#' save_key("dp_your_key_here", label = "my-laptop")
#' }
#' @export
save_key <- function(api_key,
                     base_url = default_base_url(),
                     key_id = "",
                     tier = "free",
                     label = "") {
  stopifnot(is.character(api_key), length(api_key) == 1L, nzchar(api_key))
  d <- .config_dir()
  if (!dir.exists(d)) {
    dir.create(d, recursive = TRUE, showWarnings = FALSE)
  }
  if (.Platform$OS.type != "windows") {
    Sys.chmod(d, mode = "0700")
  }
  payload <- list(
    api_key  = jsonlite::unbox(api_key),
    base_url = jsonlite::unbox(base_url),
    key_id   = jsonlite::unbox(key_id),
    tier     = jsonlite::unbox(tier),
    label    = jsonlite::unbox(label)
  )
  path <- file.path(d, .credentials_file)
  json <- jsonlite::toJSON(payload, pretty = TRUE)
  writeLines(json, path)
  if (.Platform$OS.type != "windows") {
    Sys.chmod(path, mode = "0600")
  }
  invisible(path)
}

#' @describeIn credentials Resolve any saved API key — checks
#'   \code{DOCPARSE_API_KEY} first, then the credentials file (without
#'   filtering by base URL). Used by the MCP bridge.
#' @examples
#' resolve_api_key()
#' @export
resolve_api_key <- function() {
  env_key <- Sys.getenv("DOCPARSE_API_KEY", unset = "")
  if (nzchar(env_key)) return(env_key)
  data <- .read_credentials_file()
  if (is.null(data)) return(NULL)
  data$api_key
}
