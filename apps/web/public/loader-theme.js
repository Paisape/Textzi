const loaderColor = localStorage.getItem('vuexy-initial-loader-bg') || '#FFFFFF'
const primaryColor = localStorage.getItem('vuexy-initial-loader-color') || '#F1600D'

document.documentElement.style.setProperty('--initial-loader-bg', loaderColor)
document.documentElement.style.setProperty('--initial-loader-color', primaryColor)
