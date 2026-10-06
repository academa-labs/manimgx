import { expect, test } from "bun:test"
import { readFileSync } from "node:fs"
import { runInNewContext } from "node:vm"

const script = readFileSync(new URL("../../docs/content/javascripts/manimgx.js", import.meta.url), "utf8")

function source(media, srcset) {
  const attributes = new Map(Object.entries({ media, srcset }))
  return {
    attributes,
    get media() { return attributes.get("media") },
    set media(value) { attributes.set("media", value) },
    getAttribute: name => attributes.get(name) ?? null,
    setAttribute: (name, value) => attributes.set(name, value),
  }
}

function picture() {
  return [source("(prefers-color-scheme: dark)", "/dark.svg"),
    source("(prefers-color-scheme: light)", "/light.svg")]
}

// Run the shipped script. Zensical owns resolving manual/system preferences into the
// body's scheme; this harness delivers those changes and instant-navigation events.
function page() {
  let sources = picture(), boot
  const body = source("", ""), observers = []
  body.setAttribute("data-md-color-scheme", "slate")
  const context = {
    window: {}, URL,
    location: { origin: "https://manimgx.academa.ai" },
    matchMedia: query => ({ matches: query === "(prefers-color-scheme: dark)" }),
    IntersectionObserver: class { disconnect() {} observe() {} },
    MutationObserver: class {
      constructor(callback) { this.callback = callback; observers.push(this) }
      disconnect() { this.target = null }
      observe(target, options) { this.target = target; this.options = options }
    },
    document: {
      body,
      addEventListener() {},
      querySelectorAll: selector => selector === "picture > source[media]" ? sources : [],
    },
    document$: { subscribe(callback) { boot = callback; callback() } },
  }
  runInNewContext(script, context)
  return {
    body, observers,
    get sources() { return sources },
    scheme(value) {
      body.setAttribute("data-md-color-scheme", value)
      for (const observer of observers) observer.callback()
    },
    navigate(next) { sources = next; boot() },
    reloadScript() { runInNewContext(script, context) },
  }
}

test("pictures follow the selected site theme even when the OS preference differs", () => {
  const doc = page()
  expect(doc.sources.map(s => s.media)).toEqual(["all", "not all"])
  doc.scheme("default")
  expect(doc.sources.map(s => s.media)).toEqual(["not all", "all"])
  doc.scheme("slate")
  expect(doc.sources.map(s => s.media)).toEqual(["all", "not all"])
  expect(doc.sources.map(s => s.getAttribute("srcset"))).toEqual(["/dark.svg", "/light.svg"])
  expect(doc.observers).toHaveLength(1)
  expect(doc.observers[0].target).toBe(doc.body)
  expect(doc.observers[0].options).toEqual({
    attributes: true, attributeFilter: ["data-md-color-scheme"],
  })
})

test("new and cached pages retain their source identities across instant navigation", () => {
  const doc = page()
  const restored = doc.sources.map(original => {
    const clone = source("", "")
    for (const [key, value] of original.attributes) clone.setAttribute(key, value)
    return clone
  })
  doc.scheme("default")
  doc.navigate(picture())
  expect(doc.sources.map(s => s.media)).toEqual(["not all", "all"])
  doc.navigate(restored)
  expect(doc.sources.map(s => s.media)).toEqual(["not all", "all"])
  doc.reloadScript()
  expect(doc.observers).toHaveLength(1)
  doc.scheme("slate")
  expect(doc.sources.map(s => s.media)).toEqual(["all", "not all"])
})

test("system theme changes follow Zensical while other media queries are untouched", () => {
  const doc = page()
  const density = source("(max-resolution: 1.25dppx)", "/small.avif")
  doc.navigate([...doc.sources, density])
  doc.body.setAttribute("data-md-color-media", "(prefers-color-scheme)")
  for (const scheme of ["default", "slate"]) {
    doc.scheme(scheme)
    expect(doc.sources.slice(0, 2).map(s => s.media)).toEqual(
      scheme === "slate" ? ["all", "not all"] : ["not all", "all"],
    )
    expect(density.media).toBe("(max-resolution: 1.25dppx)")
    expect(density.getAttribute("data-mx-color-media")).toBeNull()
  }
  doc.scheme("")
  expect(doc.sources.slice(0, 2).map(s => s.media)).toEqual([
    "(prefers-color-scheme: dark)", "(prefers-color-scheme: light)",
  ])
})
