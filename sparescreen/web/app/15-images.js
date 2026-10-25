  // ---- Images (covers, game art, icons) -------------------------------------

  // Shows `url` in `img` and marks `holder` with `cls`; hides it when there's no image.
  function setImage(img, holder, cls, url) {
    if (url) {
      if (img.getAttribute("src") !== url) img.setAttribute("src", url);
      if ((" " + holder.className + " ").indexOf(" " + cls + " ") < 0) holder.className += " " + cls;
    } else {
      holder.className = (" " + holder.className + " ").replace(" " + cls + " ", " ").replace(/^\s+|\s+$/g, "");
    }
  }
