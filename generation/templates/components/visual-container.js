class VisualContainer {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.visualItems = [];
    this.loadedImages = new Map();
    this.init();
  }

  init() {
    this.preloadImages().then(() => {
      this.prepareVisuals();
      this.startAnimation();
    });
  }

  preloadImages() {
    const visuals = this.container.querySelectorAll(".visual");
    const imagePromises = [];

    visuals.forEach((visual) => {
      const src = visual.getAttribute("data-src");
      const img = visual.querySelector("img");

      if (src && img) {
        const promise = new Promise((resolve, reject) => {
          const tempImg = new Image();
          tempImg.onload = () => {
            img.src = src;
            this.loadedImages.set(visual, true);
            resolve();
          };
          tempImg.onerror = reject;
          tempImg.src = src;
        });
        imagePromises.push(promise);
      }
    });

    return Promise.all(imagePromises);
  }

  prepareVisuals() {
    const visuals = this.container.querySelectorAll(".visual");
    visuals.forEach((visual) => {
      const startTime =
        parseFloat(visual.getAttribute("data-start-time")) * 1000 || 0;
      const endTime =
        parseFloat(visual.getAttribute("data-end-time")) * 1000 || 0;
      const prepareTime = startTime - 1000;

      this.visualItems.push({
        element: visual,
        startTime,
        endTime,
        prepareTime,
        hideTime: endTime - 500,
        active: false,
        prepared: false,
        hiding: false,
        captionPositioned: false,
      });
    });
  }

  positionCaption(visual) {
    const imgContainer = visual.querySelector(".img-container");
    const img = visual.querySelector("img");
    const caption = visual.querySelector(".visual-caption");

    if (img && caption && img.complete && img.naturalWidth > 0) {
      requestAnimationFrame(() => {
        const containerWidth = imgContainer.offsetWidth;
        const containerHeight = imgContainer.offsetHeight;

        // Get the natural dimensions of the image
        const naturalWidth = img.naturalWidth;
        const naturalHeight = img.naturalHeight;

        // Calculate the scale to fit the image in the container
        const scaleX = containerWidth / naturalWidth;
        const scaleY = containerHeight / naturalHeight;
        const scale = Math.min(scaleX, scaleY);

        // Calculate the actual rendered dimensions
        const renderedWidth = naturalWidth * scale;
        const renderedHeight = naturalHeight * scale;

        // Calculate the position of the image within the container
        const imgOffsetLeft = (containerWidth - renderedWidth) / 2;
        const imgOffsetBottom = (containerHeight - renderedHeight) / 2;

        caption.style.left = imgOffsetLeft + "px";
        caption.style.bottom = imgOffsetBottom + "px";
        caption.style.maxWidth = renderedWidth + "px";
      });

      return true;
    }
    return false;
  }

  updateVisuals(currentTime) {
    this.visualItems.forEach((visual) => {
      if (!visual.prepared && currentTime >= visual.prepareTime) {
        visual.element.classList.add("preparing");
        visual.prepared = true;

        setTimeout(() => {
          if (this.positionCaption(visual.element)) {
            visual.captionPositioned = true;
          }
        }, 50);
      }

      if (!visual.hiding && currentTime >= visual.hideTime && visual.active) {
        visual.element.classList.add("hiding");
        visual.element.classList.remove("active");
        visual.hiding = true;
      }

      const shouldBeActive =
        currentTime >= visual.startTime && currentTime < visual.hideTime;

      if (shouldBeActive && !visual.active && !visual.hiding) {
        if (!visual.captionPositioned) {
          setTimeout(() => {
            this.positionCaption(visual.element);
            visual.captionPositioned = true;
          }, 100);
        }

        visual.element.classList.remove("preparing");
        visual.element.classList.add("active");
        visual.active = true;
      } else if (currentTime >= visual.endTime) {
        visual.element.classList.remove("active");
        visual.element.classList.remove("hiding");
        visual.active = false;
        visual.hiding = false;
      }
    });
  }

  startAnimation() {
    const animate = () => {
      const now = performance.now();
      this.updateVisuals(now);
      requestAnimationFrame(animate);
    };

    requestAnimationFrame(animate);

    let resizeTimeout;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(() => {
        this.visualItems.forEach((visual) => {
          if (visual.active || visual.prepared) {
            this.positionCaption(visual.element);
          }
        });
      }, 100);
    });
  }
}
