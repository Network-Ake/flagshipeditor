/**
 * CSInterface — Adobe CEP CSInterface polyfill
 * Minimal implementation for FlagshipEditor
 * Full CSInterface v12 API
 */

/* eslint-disable */

function CSInterface() {
  this.hostEnvironment = JSON.parse(window.__adobe_cep__.getHostEnvironment());
}

CSInterface.prototype.getHostEnvironment = function () {
  return this.hostEnvironment;
};

CSInterface.prototype.evalScript = function (script, callback) {
  if (callback) {
    window.__adobe_cep__.evalScript(script, callback);
  } else {
    return window.__adobe_cep__.evalScript(script);
  }
};

CSInterface.prototype.getSystemPath = function (pathType) {
  var path = window.__adobe_cep__.getSystemPath(pathType);
  return path;
};

CSInterface.prototype.addEventListener = function (type, listener, obj) {
  window.__adobe_cep__.addEventListener(type, listener, obj);
};

CSInterface.prototype.removeEventListener = function (type, listener, obj) {
  window.__adobe_cep__.removeEventListener(type, listener, obj);
};

CSInterface.prototype.dispatchEvent = function (event) {
  if (typeof event.data === "object") {
    event.data = JSON.stringify(event.data);
  }
  window.__adobe_cep__.dispatchEvent(event);
};

CSInterface.prototype.requestOpenExtension = function (extensionId, params) {
  window.__adobe_cep__.requestOpenExtension(extensionId, params);
};

CSInterface.prototype.closeExtension = function () {
  window.__adobe_cep__.closeExtension();
};

CSInterface.prototype.getExtensions = function (extensionIds) {
  var extensionIdsStr = JSON.stringify(extensionIds);
  var extensionsStr = window.__adobe_cep__.getExtensions(extensionIdsStr);
  return JSON.parse(extensionsStr);
};

CSInterface.prototype.getNetworkPreferences = function () {
  return JSON.parse(window.__adobe_cep__.getNetworkPreferences());
};

CSInterface.prototype.initResourceBundle = function () {
  var resourceBundle = JSON.parse(window.__adobe_cep__.initResourceBundle());
  return resourceBundle;
};

// SystemPath constants
CSInterface.SystemPath = {
  USER_DATA: "userData",
  COMMON_FILES: "commonFiles",
  MY_DOCUMENTS: "myDocuments",
  APPLICATION: "application",
  EXTENSION: "extension",
  HOST_APPLICATION: "hostApplication",
};

// Event type constants
CSInterface.THEME_COLOR_CHANGED_EVENT = "com.adobe.csxs.events.ThemeColorChanged";

// Global instance
if (typeof window !== "undefined") {
  window.csInterface = new CSInterface();
}