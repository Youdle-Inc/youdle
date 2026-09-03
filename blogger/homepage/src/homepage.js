/* ==========================================================================
   Youdle homepage — news.youdle.io
   Dependency-free. Runs identically in the Blogger theme and in preview.py.

   Responsibilities
     1. Secondary (hamburger) menu: open/close, focus + Escape handling
     2. Analytics events from §8 of the handoff, with placement/source data
     3. The Youdle Brief signup: inline success/error states via the Mailchimp
        JSONP endpoint, degrading to a plain form POST when JS is unavailable
     4. Header "Subscribe" CTA scrolls to the signup band and focuses the field

   No essential content depends on this file; the page is fully readable and
   navigable with JavaScript disabled.
   ========================================================================== */

(function () {
  "use strict";

  var root = document.querySelector(".yd-home");
  if (!root) {
    return;
  }

  /* ---------------------------------------------------------------------
     Analytics — §8 Analytics Events
     Pushes to GTM's dataLayer and to gtag() when either is present, and
     always emits a DOM CustomEvent so any other tag manager can listen.
     --------------------------------------------------------------------- */

  function track(name, params) {
    var payload = params || {};
    payload.event_source = "homepage";

    try {
      if (Array.isArray(window.dataLayer)) {
        var forGtm = { event: name };
        for (var k in payload) {
          if (Object.prototype.hasOwnProperty.call(payload, k)) {
            forGtm[k] = payload[k];
          }
        }
        window.dataLayer.push(forGtm);
      }
      if (typeof window.gtag === "function") {
        window.gtag("event", name, payload);
      }
      document.dispatchEvent(
        new CustomEvent("youdle:analytics", {
          detail: { name: name, params: payload },
        })
      );
    } catch (err) {
      /* Analytics must never break the page. */
    }
  }

  // Any element carrying data-yd-event fires it on activation.
  root.addEventListener("click", function (event) {
    var el = event.target.closest("[data-yd-event]");
    if (!el || !root.contains(el)) {
      return;
    }
    track(el.getAttribute("data-yd-event"), {
      placement: el.getAttribute("data-yd-placement") || "",
      link_url: el.getAttribute("href") || "",
      link_text: (el.textContent || "").trim().slice(0, 120),
    });
  });

  /* ---------------------------------------------------------------------
     Story deks: strip leftover post chrome
     TEMPORARY. Blogger builds data:post.snippets.long from the post body, and
     16 of the 150 most recent posts -- including all three currently newest --
     still have a "Back to Youdle" nav link baked into the body from the old
     generator. That leaks into the dek as "<- Back to Youdle MEMPHIS, Tenn...".

     The real fix is in the repo already:
         python backfill_strip_post_chrome.py --apply --push-blogger
     which also removes the duplicate back link currently rendering on every
     article page. Once that has run, delete this block.

     Deliberately narrow: it only removes a known leading phrase, and does
     nothing when the phrase is absent.
     --------------------------------------------------------------------- */

  var CHROME_PREFIX = /^\s*(?:←|<-)?\s*Back to (?:Youdle|News Blog)\s*/i;

  Array.prototype.forEach.call(root.querySelectorAll(".yd-story__dek"), function (dek) {
    var text = dek.textContent;
    if (CHROME_PREFIX.test(text)) {
      dek.textContent = text.replace(CHROME_PREFIX, "");
    }
  });

  /* ---------------------------------------------------------------------
     Secondary menu
     --------------------------------------------------------------------- */

  var toggle = root.querySelector("[data-yd-menu-toggle]");
  var drawer = root.querySelector("[data-yd-menu]");

  if (toggle && drawer) {
    var setMenu = function (open) {
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      drawer.hidden = !open;
    };

    setMenu(false);

    toggle.addEventListener("click", function () {
      var open = toggle.getAttribute("aria-expanded") === "true";
      setMenu(!open);
      if (!open) {
        var first = drawer.querySelector("a");
        if (first) {
          first.focus();
        }
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        setMenu(false);
        toggle.focus();
      }
    });

    document.addEventListener("click", function (event) {
      if (toggle.getAttribute("aria-expanded") !== "true") {
        return;
      }
      if (!drawer.contains(event.target) && !toggle.contains(event.target)) {
        setMenu(false);
      }
    });

    // Closing on focus leaving the menu keeps keyboard and pointer in sync.
    drawer.addEventListener("focusout", function (event) {
      if (
        toggle.getAttribute("aria-expanded") === "true" &&
        !drawer.contains(event.relatedTarget) &&
        event.relatedTarget !== toggle
      ) {
        setMenu(false);
      }
    });
  }

  /* ---------------------------------------------------------------------
     Header CTA -> signup band
     --------------------------------------------------------------------- */

  var emailField = root.querySelector("#yd-brief-email");

  root.addEventListener("click", function (event) {
    var jump = event.target.closest("[data-yd-scroll-to-signup]");
    if (!jump || !emailField) {
      return;
    }
    event.preventDefault();

    var band = document.getElementById("the-youdle-brief");
    if (band) {
      var reduce =
        window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      band.scrollIntoView({
        behavior: reduce ? "auto" : "smooth",
        block: "center",
      });
    }

    // Focus after the scroll is under way so the browser does not fight it.
    window.setTimeout(function () {
      emailField.focus({ preventScroll: true });
    }, 350);
  });

  /* ---------------------------------------------------------------------
     The Youdle Brief signup
     --------------------------------------------------------------------- */

  var form = root.querySelector("[data-yd-newsletter]");

  if (form && emailField) {
    var status = root.querySelector("[data-yd-newsletter-status]");
    var submitBtn = form.querySelector("[data-yd-newsletter-submit]");
    var submitLabel = submitBtn ? submitBtn.textContent : "";
    var started = false;
    var busy = false;

    var say = function (state, message) {
      if (!status) {
        return;
      }
      status.setAttribute("data-state", state);
      status.textContent = message;
    };

    emailField.addEventListener("input", function () {
      emailField.removeAttribute("aria-invalid");
      if (!started) {
        started = true;
        track("newsletter_form_start", { placement: "homepage_newsletter" });
      }
    });

    // Mailchimp's JSONP endpoint mirrors the classic POST endpoint but
    // answers with {result, msg}, which is what makes inline states possible.
    var jsonpUrl = function (action, email) {
      var url = action.replace("/post?", "/post-json?");
      var sep = url.indexOf("?") === -1 ? "?" : "&";
      var params = [];

      // Carry every field the classic form would have sent, honeypot included.
      var fields = form.querySelectorAll("input[name]");
      for (var i = 0; i < fields.length; i++) {
        var field = fields[i];
        if (field.type === "checkbox" || field.type === "radio") {
          if (!field.checked) {
            continue;
          }
        }
        params.push(
          encodeURIComponent(field.name) +
            "=" +
            encodeURIComponent(field.name === "EMAIL" ? email : field.value)
        );
      }
      return url + sep + params.join("&");
    };

    var jsonp = function (url, onDone, onFail) {
      var cbName = "ydmc_" + Date.now() + "_" + Math.floor(Math.random() * 1e6);
      var script = document.createElement("script");
      var timer;

      var cleanup = function () {
        window.clearTimeout(timer);
        try {
          delete window[cbName];
        } catch (err) {
          window[cbName] = undefined;
        }
        if (script.parentNode) {
          script.parentNode.removeChild(script);
        }
      };

      window[cbName] = function (data) {
        cleanup();
        onDone(data);
      };

      script.onerror = function () {
        cleanup();
        onFail();
      };

      timer = window.setTimeout(function () {
        cleanup();
        onFail();
      }, 12000);

      script.src = url + "&c=" + cbName;
      document.body.appendChild(script);
    };

    // Mailchimp returns HTML inside msg (links, <br>); render it as plain text.
    var plain = function (html) {
      var tmp = document.createElement("div");
      tmp.innerHTML = String(html || "");
      return (tmp.textContent || tmp.innerText || "").trim();
    };

    form.addEventListener("submit", function (event) {
      var action = form.getAttribute("action") || "";
      // Without a Mailchimp action there is nothing to intercept; let it POST.
      if (action.indexOf("list-manage.com") === -1) {
        return;
      }

      event.preventDefault();
      if (busy) {
        return;
      }

      var email = emailField.value.trim();
      if (!email || !emailField.checkValidity()) {
        emailField.setAttribute("aria-invalid", "true");
        say("error", "Please enter a valid email address.");
        emailField.focus();
        track("newsletter_signup_error", {
          placement: "homepage_newsletter",
          reason: "invalid_email",
        });
        return;
      }

      busy = true;
      emailField.removeAttribute("aria-invalid");
      if (submitBtn) {
        // Not `disabled`: disabling the focused button drops focus to <body>
        // and a keyboard user loses their place. The `busy` flag already
        // prevents a double submit.
        submitBtn.setAttribute("aria-busy", "true");
        submitBtn.textContent = "Signing you up…";
      }
      say("pending", "Signing you up…");

      var finish = function () {
        busy = false;
        if (submitBtn) {
          submitBtn.removeAttribute("aria-busy");
          submitBtn.textContent = submitLabel;
        }
      };

      jsonp(
        jsonpUrl(action, email),
        function (data) {
          finish();
          if (data && data.result === "success") {
            say(
              "success",
              "You’re in. Look for The Youdle Brief in your inbox."
            );
            form.reset();
            track("newsletter_signup_success", {
              placement: "homepage_newsletter",
            });
          } else {
            var msg =
              plain(data && data.msg) ||
              "Something went wrong. Please try again.";
            // Mailchimp prefixes field errors with an index, e.g. "0 - ...".
            msg = msg.replace(/^\d+\s*-\s*/, "");
            say("error", msg);
            emailField.setAttribute("aria-invalid", "true");
            track("newsletter_signup_error", {
              placement: "homepage_newsletter",
              reason: msg.slice(0, 120),
            });
          }
        },
        function () {
          finish();
          say(
            "error",
            "We could not reach the signup service. Please try again in a moment."
          );
          track("newsletter_signup_error", {
            placement: "homepage_newsletter",
            reason: "network",
          });
        }
      );
    });
  }
})();
