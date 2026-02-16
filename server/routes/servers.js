const express = require("express");
const router = express.Router();

router.get("/", (req, res) => {
  res.json([
    { name: "Downtown", online: 1200 },
    { name: "Vinewood", online: 950 },
    { name: "Ocean", online: 780 }
  ]);
});

module.exports = router;
