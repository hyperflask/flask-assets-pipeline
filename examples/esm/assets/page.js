import { showAlert } from "./alert";

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btn2").addEventListener("click", () => {
        showAlert("Hello from page!");
    });
});