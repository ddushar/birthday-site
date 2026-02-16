const express = require("express");
const cors = require("cors");

const authRoutes = require("./routes/auth");
const serverRoutes = require("./routes/servers");
const donateRoutes = require("./routes/donate");

const app = express();

app.use(cors());
app.use(express.json());

app.use("/api/auth", authRoutes);
app.use("/api/servers", serverRoutes);
app.use("/api/donate", donateRoutes);

app.listen(5000, () => {
  console.log("Kilop Backend running on port 5000");
});
