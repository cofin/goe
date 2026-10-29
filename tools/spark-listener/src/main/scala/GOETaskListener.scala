package com.gluent.spark

import org.apache.spark.scheduler._
import org.json4s.JsonDSL._
import org.json4s.jackson.JsonMethods._
import org.slf4j.{Logger, LoggerFactory}

class GOETaskListener extends SparkListener {
  private val logger: Logger = LoggerFactory.getLogger("GOETaskListener")

  override def onTaskEnd(taskEnd: SparkListenerTaskEnd): Unit = {
    val taskInfo = taskEnd.taskInfo
    val taskMetrics = taskEnd.taskMetrics
    val outputMetrics = taskMetrics.outputMetrics

    if (outputMetrics.recordsWritten > 0) {
      val json = ("stageId" -> taskEnd.stageId) ~
        ("taskId" -> taskInfo.taskId) ~
        ("status" -> taskInfo.status) ~
        ("recordsWritten" -> outputMetrics.recordsWritten) ~
        ("bytesWritten" -> outputMetrics.bytesWritten)

      logger.info(compact(render(json)))
    }
  }
}
