/*
 * SPDX-FileCopyrightText: 2016 The GOE Authors
 * SPDX-License-Identifier: Apache-2.0
 */

ThisBuild / organization := "com.goe"
ThisBuild / scalaVersion := sys.props.getOrElse("scalaVersion", "2.12.18")
ThisBuild / version      := "1.0"

val sparkVersion = sys.props.getOrElse("sparkVersion", "3.2.0")

lazy val root = (project in file("."))
  .settings(
    name := "spark-" + sparkVersion + "-listener",
    artifactName := { (sv: ScalaVersion, module: ModuleID, artifact: Artifact) =>
      "spark-" + sparkVersion + "-listener" + "_" + sv.binary +  "-" + module.revision + "." + artifact.extension
    },
    libraryDependencies += "org.apache.spark" %% "spark-core" % sparkVersion,
  )
