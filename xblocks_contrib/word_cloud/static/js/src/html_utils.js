function setHtml(element, html) {
  return $(element).html(ensureHtml(html).toString());
}

function interpolateHtml(formatString, parameters) {
  var result = StringInterpolate(
    ensureHtml(formatString).toString(),
    mapObject(parameters, ensureHtml)
  );
  return HTML(result);
}

function ensureHtml(html) {
  if (html instanceof HtmlSnippet) {
    return html;
  } else {
    return HTML(escape(html));
  }
}

function HtmlSnippet(htmlString) {
  this.text = htmlString;
}

HtmlSnippet.prototype.valueOf = function () {
  return this.text;
};
HtmlSnippet.prototype.toString = function () {
  return this.text;
};

function StringInterpolate(formatString, parameters) {
  return formatString.replace(/{\w+}/g,
    function (parameter) {
      var parameterName = parameter.slice(1, -1);
      return String(parameters[parameterName]);
    });
}

HTML = function (htmlString) {
  return new HtmlSnippet(htmlString);
};

function mapObject(obj, iteratee) {
  var result = {};
  for (var key in obj) {
    if (obj.hasOwnProperty(key)) {
      result[key] = iteratee(obj[key], key, obj);
    }
  }
  return result;
}

function escape(string) {
  // If the string is null or undefined, return an empty string
  if (string == null) return '';

  // Create a map of characters to their escaped equivalents
  var escapeMap = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#x27;',
    '`': '&#x60;'
  };

  // Create a regular expression to match characters that need to be escaped
  var escaper = /[&<>"'`]/g;

  // Replace each character in the string with its escaped equivalent
  return ('' + string).replace(escaper, function (match) {
    return escapeMap[match];
  });
}
