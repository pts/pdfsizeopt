/*
 * pdfsizeopt_winstub.c: Start Python on Win32.
 * by pts@fazekas.hu at Wed Jun 27 14:07:04 CEST 2012
 *
 * Compile with: i686-w64-mingw32-gcc -mconsole -s -Os -W -Wall -Wextra -o ../pdfsizeopt.exe pdfsizeopt_winstub.c
 */

#include <errno.h>
#include <limits.h>  /* PATH_MAX is 259. */
#include <process.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

/* Shorter than <windows.h>, GetCommandLine() is defined in <winbase.h>. */
#include <stdarg.h>
#include <windef.h>
#include <winbase.h>

#define FILE_SEP '\\'
#define PATH_SEP ';'

#define CMDLINE_MAX 16384

static char is_in_dir(const char *file, const char *p, const char *q) {
  struct stat st;
  char pathname[PATH_MAX + 1];
  int len = (q - p) + 1 + strlen(file);
  if (len > PATH_MAX) len = PATH_MAX;
  strncpy(pathname, p, q - p);
  if (len > q - p) {
    pathname[q - p] = FILE_SEP;
    strncpy(pathname + (q - p) + 1, file, len - (q - p) - 1);
  } else {
    if (q - p < PATH_MAX) pathname[q - p] = '\0';
  }
  pathname[len] = '\0';
  return 0 == stat(pathname, &st) && S_ISREG(st.st_mode);
}

static char is_file(const char *pathname) {
  struct stat st;
  return 0 == stat(pathname, &st) && S_ISREG(st.st_mode);
}

static void find_on_path(const char *prog, char *dir_out) {
  const char *path = getenv("PATH"), *p, *q;
  char is_qq;
  if (path != NULL || *path != '\0') {
    p = path;
    while (*p != '\0') {
      while (*p == PATH_SEP) {
        ++p;
      }
      if (*p == '\0') break;
      if ((is_qq = (*p == '"'))) {
        /* This is probably not the right way of removing "s,
         * but it happens to work with "...";... At least filenames can't
         * contain ", so the \..." unescaping hell won't happen for valid
         * filenames.
         */
        q = ++p;
        while (*q != '\0' && *q != '"') ++q;
      } else {
        q = p;
        while (*q != '\0' && *q != PATH_SEP) ++q;
      }
      if (is_in_dir(prog, p, q)) {
        if (q - p > PATH_MAX) {
          q = p + PATH_MAX;
        }
        memcpy(dir_out, p, q - p);
        dir_out[q - p] = '\0';
        return;
      }
      p = q;
      if (is_qq && *p == '"') ++p;
    }
  }
  *dir_out = '\0';  /* Not found. */
}

/* Appends zero-terminated input p to out...outend, returns the position in
 * out after the output. Truncates silently.
 */
static char *add_verbatimz(const char *p, char *out, const char *outend) {
  for (; *p != '\0' && out != outend; *out++ = *p++) {}
  return out;
}

/* Escapes a command-line argument between p and pend to out, returns the
 * position in out after the output. Truncates silently.
 *
 * Does the escaping according to inverse of the rules defined in
 *
 * * https://stackoverflow.com/a/4094897/97248
 * * https://msdn.microsoft.com/en-us/library/a1y7w461.aspx
 *
 * The following characters need escaping:
 * space, tab, %, ", <, >, &, |.
 * If the input contains none of these, the output is same as the
 * input. Otherwise, the output looks like "...", and within the "s:
 *
 * * \s not followed by a " are kept intact
 * * \s followed by a " are doubled and the " is escaped as \"
 * * " (not preceded by a \) is escaped as \"
 * * anything else is kept intact
 */
static char *add_escaped(const char *p, const char *pend,
                         char *out, const char *outend) {
  register char c;
  const char *q = p;
  while (q != pend && (c = *q) != ' ' && c != '\t' && c != '%' &&
         c != '"' && c != '<' && c != '>' && c != '&' && c != '|') {
    ++q;
  }
  if (q == pend && p != pend) {  /* No need for escaping. */
    for (; p != pend && out != outend; *out++ = *p++) {}
  } else {
    if (out != outend) *out++ = '"';
    while (p != pend) {
      if ((c = *p) == '"') {  /* Escape " as \" */
       do_qq:
        if (out != outend) *out++ = '\\';
        goto do_verbatim;
      } else if (c == '\\') {
        for (q = p; q != pend && *q == '\\'; ++q) {}
        if (q == pend || *q != '"') {  /* Copy verbatim. */
          for (; p != q && out != outend; *out++ = *p++) {}
          if (out == outend) break;
        } else {
          for (; p != q; ++p) {
            if (out != outend) *out++ = '\\';
            if (out != outend) *out++ = '\\';
          }
          goto do_qq;
        }
      } else {  /* Copy character verbatim. */
       do_verbatim:
        if (out != outend) *out++ = *p;
        ++p;
      }
    }
    if (out != outend) *out++ = '"';
  }
  return out;
}

/* Skips a single command-line argument in the beginning of p.
 *
 * Does the parsing according to the rules defined in
 *
 * * https://stackoverflow.com/a/4094897/97248
 * * https://msdn.microsoft.com/en-us/library/a1y7w461.aspx
 *
 * Most of this is unnecessary for skipping filenames, because filenames
 * cannot contain \\ or \".
 */
const char *skip_arg(const char *p) {
  register char c;
  const char *q;
  while ((c = *p) == ' ' || c == '\t') ++p;
  for (;;) {
    while ((c = *p++) != ' ' && c != '\t' && c != '\0' && c != '"' &&
           c != '\\') {}
    if (c == ' ' || c == '\t' || c == '\0') break;
    if (c == '"') {
     do_qq:
      for (;;) {
        for (; (c = *p) != '\0' && c != '\\' && c != '"'; ++p) {}
        if (c == '\0') goto at_end;
        if (c == '"') { ++p; break; }
        q = ++p;  /* Skip over the '\\'. */
        for (; *p == '\\'; ++p) {}
        if (*p == '"') {
          ++p;
          if ((q - p) % 2 == 0) break;
        }
      }
    } else {  /* c == '\\'. */
      q = p;
      for (; *p == '\\'; ++p) {}
      if (*p == '"') {
        ++p;
        if ((q - p) % 2 == 0) goto do_qq;
      }
    }
  }
  while ((c = *p) == ' ' || c == '\t') ++p;
 at_end:
  return p;
}

/* FILE_SEP inlined here. */
static const char python_exe[] = "pdfsizeopt_win32exec\\pdfsizeopt_python.exe";
static const char pdfsizeopt_py0[] = "pdfsizeopt";
static const char pdfsizeopt_py1[] = "pdfsizeopt.single";

int main(int argc, char **argv) {
  char python_bin[PATH_MAX + 1], argv0_bin[PATH_MAX + 1], *p, *q;
  char prog_py[PATH_MAX + 2];
  char cmdline[CMDLINE_MAX], *cp, *cend = cmdline + sizeof(cmdline);
  const char *cmdline_argv[2];
  int i;
  (void)argc;
  p = argv[0];
  q = NULL;
  while (*p != '\0') {
    if (*p++ == FILE_SEP) q = p;
  }
  if (q == NULL) {  /* Try to find argv[0] on $PATH. */
    p = argv[0];
    strncpy(argv0_bin, p, sizeof argv0_bin);
    q = NULL;
    while (*p != '\0') {
      if (*p++ == '.') q = p;
    }
    if (q == NULL) {
      argv0_bin[sizeof argv0_bin - 5] = '\0';
      strcat(argv0_bin, ".exe");
    } else {
      argv0_bin[sizeof argv0_bin - 1] = '\0';
    }
    find_on_path(argv0_bin, python_bin);
  } else {  /* Put dirname(argv[0]) to python_bin. */
    p = argv[0];
    --q;
    if (q - p > PATH_MAX) {
      q = p + PATH_MAX;
    }
    strncpy(python_bin, p, q - p);
    python_bin[q - p] = '\0';
  }

  if (python_bin[0] == '\0') {
    python_bin[0] = '.';
    python_bin[1] = '\0';
  }
  p = python_bin + strlen(python_bin);
  /* Remove trailing backslashes from python_bin. */
  while (p != python_bin && p[-1] == FILE_SEP) --p;
  *p = '\0';

  strcpy(prog_py, python_bin);

  i = strlen(python_bin);
  if (i + strlen(python_exe) > PATH_MAX) {
    i = PATH_MAX - strlen(python_exe);
  }
  python_bin[i] = FILE_SEP;
  strcpy(python_bin + i + 1, python_exe);

  i = strlen(prog_py);
  if (i + strlen(pdfsizeopt_py0) > PATH_MAX) {
    i = PATH_MAX - strlen(pdfsizeopt_py0);
  }
  if (i + strlen(pdfsizeopt_py1) > PATH_MAX) {
    i = PATH_MAX - strlen(pdfsizeopt_py1);
  }
  prog_py[i++] = FILE_SEP;
  strcpy(prog_py + i, pdfsizeopt_py0);
  if (!is_file(prog_py)) {
    strcpy(prog_py + i, pdfsizeopt_py1);
    if (!is_file(prog_py)) {
      fprintf(stderr, "error: Python script missing: %s\n", prog_py);
      return 121;
    }
  }

  cp = cmdline;
  cp = add_verbatimz("python ", cp, cend);
  /* strcat(prog_py, "  <head>\"foo\\\\bar\\\\\"baz?"); */
  cp = add_escaped(prog_py, prog_py + strlen(prog_py), cp, cend);
  if (cp != cend) *cp++ = ' ';
  /* For debugging: we could have 2 skip_arg(...) calls. */
  cp = add_verbatimz(skip_arg(GetCommandLine()), cp, cend);
  if (cp == cend) {
    fprintf(stderr, "error: output command-line too long\n");
    return 122;
  }
  if (cp[-1] == ' ') --cp;
  *cp = '\0';
  /* printf("cmdline=(%s)\n", cmdline); return 0; */

  cmdline_argv[0] = cmdline;
  cmdline_argv[1] = NULL;

  /* execv(...) and P_OVERLAY don't work well in wine-1.2.2 and Windows XP,
   * because they make this process return before the started process finishes.
   *
   * It's undocumented, but spawvn just joins cmdline_argv with spaces,
   * which is not what we would want with argv (because it's already split
   * and unescaped). So we use GetCommandLine() in cmdline_argv, which is
   * escaped.
   *
   * Casting to (void*) needed to avoid different warnings (different
   * declarations) with i586-mingw32msvc-gcc and i686-w64-mingw32-gcc.
   */
  i = spawnv(P_WAIT, python_bin, (void*)cmdline_argv);
  if (i < 0) {
    fprintf(stderr, "error: could not start %s: %s\n",
            python_bin, strerror(errno));
    return 120;
  }
  return i;
}
