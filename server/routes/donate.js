const express = require("express");
const router = express.Router();

router.post("/", (req, res) => {
  const { package } = req.body;
  res.json({ message: `Оплата пакета ${package} создана` });
});

module.exports = router;
