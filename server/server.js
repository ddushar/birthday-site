const express = require("express");
const cors = require("cors");

const authRoutes = require("./routes/auth");
const serverRoutes = require("./routes/servers");
const donateRoutes = require("./routes/donate");

const app = express();
app.use(cors()); // разрешить запросы с любого источника
app.use(express.json());

app.use("/api/auth", authRoutes);
app.use("/api/servers", serverRoutes);
app.use("/api/donate", donateRoutes);

// ⚡ использовать порт от Render или 5000 по умолчанию
const PORT = process.env.PORT || 5000;
app.listen(PORT, () => co
