import { showAlert } from "./alert";
import "./base.css";

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("btn").addEventListener("click", () => {
        showAlert("Hello, world!");
    });
});