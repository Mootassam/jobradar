/* Practice form: show what would have been submitted - nothing leaves the page. */
document.getElementById("application_form").addEventListener("submit", function (e) {
  e.preventDefault();
  var out = {};
  new FormData(e.target).forEach(function (v, k) { out[k] = v instanceof File ? (v.name ? v.name + " (" + v.size + " bytes)" : "") : v; });
  var box = document.getElementById("result");
  box.hidden = false;
  box.textContent = "Practice only - this is what the company would receive:\n\n" + JSON.stringify(out, null, 2);
});
